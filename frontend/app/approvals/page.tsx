"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import {
  approvalNode,
  approvalPrompt,
  resumeInput,
  runInputPrompt,
  waitingHumanRuns,
  type ApprovalDecision,
} from "@/lib/approval";
import { api } from "@/lib/api";
import {
  liveRunIdsFromRuns,
  useRunsListLiveSync,
} from "@/lib/useRunLiveSync";
import type { Run } from "@/lib/types";

function InboxRow({ run }: { run: Run }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const resume = useMutation({
    mutationFn: (decision: ApprovalDecision) =>
      api.resumeRun(run.id, { input: resumeInput(decision) }),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["run", run.id] });
      queryClient.invalidateQueries({ queryKey: ["run-audit", run.id] });
    },
    onError: (err) => setError(String(err)),
  });

  const prompt = approvalPrompt(run.output);
  const node = approvalNode(run.output);
  const inputPrompt = runInputPrompt(run.input);

  return (
    <tr className="hover:bg-bg/50 align-top">
      <td className="px-4 py-3 font-mono">
        <Link className="hover:text-accent" href={`/runs/${run.id}`}>
          {run.id}
        </Link>
        <div className="text-xs text-muted mt-1">
          {run.adapter}
          {node ? ` · node ${node}` : ""}
        </div>
      </td>
      <td className="px-4 py-3">
        <p className="text-sm">{prompt}</p>
        {inputPrompt ? (
          <p className="text-xs text-muted mt-1 truncate">input: {inputPrompt}</p>
        ) : null}
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={run.status} />
      </td>
      <td className="px-4 py-3 text-xs text-muted whitespace-nowrap">
        {new Date(run.updated_at).toLocaleString()}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-2 justify-end">
          <button
            type="button"
            className="rounded bg-good/20 text-good px-2.5 py-1 text-xs hover:bg-good/30 disabled:opacity-50"
            disabled={resume.isPending}
            onClick={() => resume.mutate("approved")}
          >
            Approve
          </button>
          <button
            type="button"
            className="rounded bg-bad/20 text-bad px-2.5 py-1 text-xs hover:bg-bad/30 disabled:opacity-50"
            disabled={resume.isPending}
            onClick={() => resume.mutate("rejected")}
          >
            Reject
          </button>
          <Link
            href={`/runs/${run.id}`}
            className="rounded border border-border px-2.5 py-1 text-xs hover:bg-surface"
          >
            Review
          </Link>
        </div>
        {error ? <p className="text-bad text-xs mt-2 text-right">{error}</p> : null}
      </td>
    </tr>
  );
}

export default function ApprovalsPage() {
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.listRuns,
    refetchInterval: 10_000,
  });

  const liveRunIds = useMemo(
    () => liveRunIdsFromRuns(runs.data),
    [runs.data],
  );
  useRunsListLiveSync(liveRunIds);

  const pending = waitingHumanRuns(runs.data);

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Approvals</h1>
          <p className="text-xs text-muted mt-1">
            Runs paused at a human node. Approve or reject to resume from the
            latest checkpoint.
          </p>
        </div>
        <span className="text-xs text-muted">
          {pending.length === 1 ? "1 waiting" : `${pending.length} waiting`}
        </span>
      </header>

      {runs.isLoading ? (
        <p className="text-muted">Loading…</p>
      ) : runs.error ? (
        <p className="text-bad">Failed to load runs: {String(runs.error)}</p>
      ) : pending.length > 0 ? (
        <table className="w-full text-sm border border-border rounded-lg overflow-hidden bg-surface">
          <thead className="text-left text-muted bg-bg">
            <tr>
              <th className="px-4 py-2 font-medium">Run</th>
              <th className="px-4 py-2 font-medium">Request</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Updated</th>
              <th className="px-4 py-2 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {pending.map((run) => (
              <InboxRow key={run.id} run={run} />
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-muted text-sm">
          No runs are waiting for approval.{" "}
          <Link href="/runs" className="hover:text-accent">
            Browse runs
          </Link>
        </p>
      )}
    </div>
  );
}
