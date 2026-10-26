"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { CheckpointMarker } from "@/components/CheckpointMarker";
import { api } from "@/lib/api";
import { latestCheckpoint } from "@/lib/checkpoints";
import type { Checkpoint, RunStatus } from "@/lib/types";

interface Props {
  runId: string;
  status: RunStatus;
  checkpoints: Checkpoint[];
}

export function CheckpointPanel({ runId, status, checkpoints }: Props) {
  const queryClient = useQueryClient();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["run", runId] });

  const retry = useMutation({
    mutationFn: (checkpointIndex?: number) =>
      api.retryRun(
        runId,
        checkpointIndex != null ? { checkpoint_index: checkpointIndex } : undefined,
      ),
    onSuccess: invalidate,
  });

  if (checkpoints.length === 0 && status !== "failed") {
    return null;
  }

  const latest = latestCheckpoint(checkpoints);

  return (
    <section className="rounded-lg border border-border bg-surface p-4 space-y-3">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-medium">Checkpoints</h2>
        {status === "failed" && checkpoints.length > 0 ? (
          <button
            type="button"
            className="rounded border border-accent/40 text-accent px-3 py-1.5 text-sm hover:bg-accent/10 disabled:opacity-50"
            disabled={retry.isPending}
            onClick={() => retry.mutate(latest?.index)}
          >
            {retry.isPending
              ? "Retrying…"
              : latest
                ? `Retry from CP #${latest.index}`
                : "Retry"}
          </button>
        ) : null}
      </div>

      {checkpoints.length === 0 ? (
        <p className="text-xs text-muted">No checkpoints saved yet.</p>
      ) : (
        <ol className="space-y-2">
          {checkpoints.map((cp) => (
            <li
              key={cp.id}
              className="flex items-center justify-between gap-3 rounded border border-border bg-bg px-3 py-2 text-sm"
            >
              <div className="flex items-center gap-3 min-w-0">
                <CheckpointMarker checkpoint={cp} />
                <span className="text-xs text-muted truncate">
                  {new Date(cp.created_at).toLocaleString()}
                </span>
              </div>
              {status === "failed" ? (
                <button
                  type="button"
                  className="shrink-0 text-xs text-accent hover:underline disabled:opacity-50"
                  disabled={retry.isPending}
                  onClick={() => retry.mutate(cp.index)}
                >
                  Retry here
                </button>
              ) : null}
            </li>
          ))}
        </ol>
      )}

      {retry.error ? (
        <p className="text-bad text-xs">{String(retry.error)}</p>
      ) : null}
    </section>
  );
}
