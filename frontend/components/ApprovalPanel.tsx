"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  approvalDraft,
  approvalNode,
  approvalPrompt,
  resumeInput,
  type ApprovalDecision,
} from "@/lib/approval";
import { api } from "@/lib/api";
import { latestCheckpoint } from "@/lib/checkpoints";
import type { Checkpoint, Message, RunStatus } from "@/lib/types";

interface Props {
  runId: string;
  status: RunStatus;
  output: Record<string, unknown> | null;
  messages?: Message[];
  checkpoints?: Checkpoint[];
}

function parseExtraJson(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  const parsed: unknown = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Extra input must be a JSON object");
  }
  return parsed as Record<string, unknown>;
}

export function ApprovalPanel({
  runId,
  status,
  output,
  messages = [],
  checkpoints = [],
}: Props) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [extraJson, setExtraJson] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["run", runId] });
    queryClient.invalidateQueries({ queryKey: ["runs"] });
    queryClient.invalidateQueries({ queryKey: ["run-audit", runId] });
  };

  const resume = useMutation({
    mutationFn: (decision: ApprovalDecision) => {
      const extra = parseExtraJson(extraJson);
      return api.resumeRun(runId, {
        input: resumeInput(decision, { note, extra }),
      });
    },
    onSuccess: invalidate,
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelRun(runId),
    onSuccess: invalidate,
  });

  if (status !== "waiting_human") return null;

  const prompt = approvalPrompt(output);
  const node = approvalNode(output);
  const draft = approvalDraft(output, messages);
  const checkpoint = latestCheckpoint(checkpoints);
  const busy = resume.isPending || cancel.isPending;

  return (
    <section className="rounded-lg border border-warn/40 bg-warn/5 p-4 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1 min-w-0">
          <h2 className="font-medium text-warn">Waiting for approval</h2>
          <p className="text-sm">{prompt}</p>
          <div className="text-xs text-muted font-mono">
            {node ? <span>node {node}</span> : null}
            {node && checkpoint ? " · " : null}
            {checkpoint
              ? `resume from CP #${checkpoint.index}${
                  checkpoint.label ? ` (${checkpoint.label})` : ""
                }`
              : null}
          </div>
        </div>
      </div>

      {draft ? (
        <div className="rounded border border-border bg-bg p-3 space-y-1">
          <div className="text-xs uppercase tracking-wide text-muted">
            Agent draft
          </div>
          <pre className="text-xs font-mono whitespace-pre-wrap text-muted max-h-48 overflow-auto">
            {draft}
          </pre>
        </div>
      ) : null}

      <label className="block space-y-1">
        <span className="text-xs uppercase tracking-wide text-muted">
          Note (optional)
        </span>
        <input
          className="w-full rounded border border-border bg-bg px-3 py-2 text-sm"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Reason for this decision"
          disabled={busy}
        />
      </label>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded bg-good/20 text-good px-3 py-1.5 text-sm hover:bg-good/30 disabled:opacity-50"
          disabled={busy}
          onClick={() => resume.mutate("approved")}
        >
          {resume.isPending && resume.variables === "approved"
            ? "Approving…"
            : "Approve"}
        </button>
        <button
          type="button"
          className="rounded bg-bad/20 text-bad px-3 py-1.5 text-sm hover:bg-bad/30 disabled:opacity-50"
          disabled={busy}
          onClick={() => resume.mutate("rejected")}
        >
          {resume.isPending && resume.variables === "rejected"
            ? "Rejecting…"
            : "Reject"}
        </button>
        <button
          type="button"
          className="rounded border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-50"
          disabled={busy}
          onClick={() => cancel.mutate()}
        >
          {cancel.isPending ? "Cancelling…" : "Cancel run"}
        </button>
        <button
          type="button"
          className="rounded px-3 py-1.5 text-sm text-muted hover:text-text"
          onClick={() => setShowAdvanced((open) => !open)}
        >
          {showAdvanced ? "Hide extra JSON" : "Extra JSON"}
        </button>
      </div>

      {showAdvanced ? (
        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-muted">
            Extra resume fields (merged into human input)
          </span>
          <textarea
            className="w-full rounded border border-border bg-bg px-3 py-2 text-xs font-mono min-h-[4rem]"
            value={extraJson}
            onChange={(e) => setExtraJson(e.target.value)}
            placeholder='{"key": "value"}'
            disabled={busy}
          />
        </label>
      ) : null}

      {resume.error ? (
        <p className="text-bad text-xs">{String(resume.error)}</p>
      ) : null}
      {cancel.error ? (
        <p className="text-bad text-xs">{String(cancel.error)}</p>
      ) : null}
    </section>
  );
}
