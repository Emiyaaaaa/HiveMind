"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { waitingHumanRuns } from "@/lib/approval";
import { api } from "@/lib/api";
import {
  liveRunIdsFromRuns,
  useRunsListLiveSync,
} from "@/lib/useRunLiveSync";
import { formatCostUsd, hasUsageMetrics } from "@/lib/usage";

export default function RunsPage() {
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.listRuns,
  });

  const liveRunIds = useMemo(
    () => liveRunIdsFromRuns(runs.data),
    [runs.data],
  );

  useRunsListLiveSync(liveRunIds);

  const pendingApprovals = waitingHumanRuns(runs.data);

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Runs</h1>
        <div className="flex items-center gap-3 text-xs text-muted">
          <Link href="/approvals" className="hover:text-accent">
            Approvals
            {pendingApprovals.length > 0
              ? ` (${pendingApprovals.length})`
              : ""}
          </Link>
          <Link href="/regression" className="hover:text-accent">
            Regression suite
          </Link>
          <span>
            {liveRunIds.length > 0
              ? `live via SSE (${liveRunIds.length} active)`
              : "updates on refresh"}
          </span>
        </div>
      </header>

      {pendingApprovals.length > 0 ? (
        <Link
          href="/approvals"
          className="block rounded-lg border border-warn/40 bg-warn/5 px-4 py-3 text-sm hover:bg-warn/10"
        >
          <span className="text-warn font-medium">
            {pendingApprovals.length === 1
              ? "1 run is waiting for approval"
              : `${pendingApprovals.length} runs are waiting for approval`}
          </span>
          <span className="text-muted"> · open the inbox</span>
        </Link>
      ) : null}

      {runs.isLoading ? (
        <p className="text-muted">Loading…</p>
      ) : runs.data && runs.data.length > 0 ? (
        <table className="w-full text-sm border border-border rounded-lg overflow-hidden bg-surface">
          <thead className="text-left text-muted bg-bg">
            <tr>
              <th className="px-4 py-2 font-medium">Run</th>
              <th className="px-4 py-2 font-medium">Adapter</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Usage</th>
              <th className="px-4 py-2 font-medium">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {runs.data.map((r) => (
              <tr
                key={r.id}
                className={
                  r.status === "waiting_human"
                    ? "hover:bg-warn/10 bg-warn/5"
                    : "hover:bg-bg/50"
                }
              >
                <td className="px-4 py-2 font-mono">
                  <Link className="hover:text-accent" href={`/runs/${r.id}`}>
                    {r.id}
                  </Link>
                </td>
                <td className="px-4 py-2 font-mono text-xs">{r.adapter}</td>
                <td className="px-4 py-2">
                  <StatusBadge status={r.status} />
                </td>
                <td className="px-4 py-2 text-xs font-mono text-muted">
                  {hasUsageMetrics(r.usage) ? (
                    <span>
                      {r.usage.tokens_in + r.usage.tokens_out > 0
                        ? `${r.usage.tokens_in + r.usage.tokens_out} tok · `
                        : ""}
                      {r.usage.step_count > 0
                        ? `${r.usage.step_count} steps · `
                        : ""}
                      <span className="text-accent">
                        {formatCostUsd(r.usage.cost_usd)}
                      </span>
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-2 text-xs text-muted">
                  {new Date(r.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-muted">No runs yet.</p>
      )}
    </div>
  );
}
