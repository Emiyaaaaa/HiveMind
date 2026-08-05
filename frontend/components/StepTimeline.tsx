"use client";

import clsx from "clsx";
import {
  memo,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";

import { CheckpointMarker } from "@/components/CheckpointMarker";
import { StatusBadge } from "@/components/StatusBadge";
import { formatCostUsd } from "@/lib/usage";
import type { Checkpoint, RunStatus, Step, ToolCall } from "@/lib/types";

interface Props {
  steps: Step[];
  checkpointsByStepId?: Map<string, Checkpoint[]>;
}

const EMPTY_CHECKPOINTS: Checkpoint[] = [];

const statusDot: Record<RunStatus, string> = {
  pending: "bg-muted border-muted",
  running: "bg-accent border-accent animate-pulse",
  succeeded: "bg-good border-good",
  failed: "bg-bad border-bad",
  cancelled: "bg-muted border-muted",
  waiting_human: "bg-warn border-warn",
};

const statusBar: Record<RunStatus, string> = {
  pending: "bg-muted/40",
  running: "bg-accent/60",
  succeeded: "bg-good/60",
  failed: "bg-bad/60",
  cancelled: "bg-muted/40",
  waiting_human: "bg-warn/60",
};

const statusRail: Record<RunStatus, string> = {
  pending: "bg-border",
  running: "bg-accent/40",
  succeeded: "bg-good/40",
  failed: "bg-bad/40",
  cancelled: "bg-border",
  waiting_human: "bg-warn/40",
};

const JSON_PREVIEW_CHARS = 4_000;

function formatLatency(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  const mins = Math.floor(ms / 60_000);
  const secs = Math.round((ms % 60_000) / 1000);
  return `${mins}m ${secs}s`;
}

function formatRelativeTime(iso: string): string {
  return new Date(iso).toLocaleTimeString();
}

function stepHasDetails(s: Step): boolean {
  return (
    s.tool_calls.length > 0 ||
    s.output != null ||
    s.error != null ||
    Object.keys(s.input).length > 0
  );
}

function shouldAutoExpand(s: Step): boolean {
  return s.status === "failed" || s.error != null;
}

interface StepStats {
  sorted: Step[];
  maxLatency: number;
  totalLatency: number;
  statusCounts: Partial<Record<RunStatus, number>>;
  detailIds: string[];
}

function computeStats(steps: Step[]): StepStats {
  const sorted = [...steps].sort((a, b) => a.index - b.index);
  let maxLatency = 0;
  let totalLatency = 0;
  const statusCounts: Partial<Record<RunStatus, number>> = {};
  const detailIds: string[] = [];

  for (const s of sorted) {
    if (s.latency_ms != null) {
      totalLatency += s.latency_ms;
      if (s.latency_ms > maxLatency) maxLatency = s.latency_ms;
    }
    statusCounts[s.status] = (statusCounts[s.status] ?? 0) + 1;
    if (stepHasDetails(s)) detailIds.push(s.id);
  }

  return { sorted, maxLatency, totalLatency, statusCounts, detailIds };
}

export function StepTimeline({ steps, checkpointsByStepId }: Props) {
  const deferredSteps = useDeferredValue(steps);
  const { sorted, maxLatency, totalLatency, statusCounts, detailIds } =
    useMemo(() => computeStats(deferredSteps), [deferredSteps]);

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  // Auto-expand failed / errored steps as they appear (additive, never collapses).
  useEffect(() => {
    const autoIds = sorted.filter(shouldAutoExpand).map((s) => s.id);
    if (autoIds.length === 0) return;
    setExpanded((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of autoIds) {
        if (!next.has(id)) {
          next.add(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [sorted]);

  const toggle = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const expandAll = useCallback(() => {
    setExpanded(new Set(detailIds));
  }, [detailIds]);

  const collapseAll = useCallback(() => {
    setExpanded(new Set());
  }, []);

  if (sorted.length === 0) {
    return (
      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="font-medium mb-2">Step timeline</h2>
        <p className="text-xs text-muted">No steps yet.</p>
      </section>
    );
  }

  const allExpanded =
    detailIds.length > 0 && detailIds.every((id) => expanded.has(id));

  return (
    <section className="rounded-lg border border-border bg-surface p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="font-medium">Step timeline</h2>
          <p className="text-xs text-muted">
            {sorted.length} step{sorted.length === 1 ? "" : "s"}
            {totalLatency > 0
              ? ` · Σ latency ${formatLatency(totalLatency)}`
              : ""}
            {maxLatency > 0 ? ` · max ${formatLatency(maxLatency)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1.5">
            {(Object.entries(statusCounts) as [RunStatus, number][]).map(
              ([status, count]) => (
                <span
                  key={status}
                  className="inline-flex items-center gap-1.5 text-xs text-muted"
                >
                  <span
                    className={clsx(
                      "inline-block size-2 rounded-full border",
                      statusDot[status],
                    )}
                  />
                  {count} {status}
                </span>
              ),
            )}
          </div>
          {detailIds.length > 0 ? (
            <button
              type="button"
              className="text-xs text-accent hover:underline ml-1"
              onClick={allExpanded ? collapseAll : expandAll}
            >
              {allExpanded ? "Collapse all" : "Expand all"}
            </button>
          ) : null}
        </div>
      </div>

      {maxLatency > 0 ? (
        <div className="space-y-1.5">
          <div className="text-xs text-muted uppercase tracking-wide">
            Latency by node
          </div>
          <ol className="space-y-1.5">
            {sorted.map((s) => {
              const pct =
                s.latency_ms != null && maxLatency > 0
                  ? Math.max(2, (s.latency_ms / maxLatency) * 100)
                  : 0;
              return (
                <li
                  key={`bar-${s.id}`}
                  className="flex items-center gap-3 text-xs"
                >
                  <span className="w-24 shrink-0 truncate font-mono text-muted">
                    #{s.index} {s.node}
                  </span>
                  <div className="flex-1 h-2 rounded bg-bg overflow-hidden">
                    <div
                      className={clsx(
                        "h-full rounded transition-[width] duration-300",
                        statusBar[s.status],
                      )}
                      style={{ width: `${pct}%` }}
                      title={formatLatency(s.latency_ms)}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right font-mono tabular-nums text-muted">
                    {formatLatency(s.latency_ms)}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}

      <ol className="relative space-y-0">
        {sorted.map((s, i) => (
          <StepItem
            key={s.id}
            step={s}
            isLast={i === sorted.length - 1}
            isOpen={expanded.has(s.id)}
            checkpoints={checkpointsByStepId?.get(s.id) ?? EMPTY_CHECKPOINTS}
            maxLatency={maxLatency}
            onToggle={toggle}
          />
        ))}
      </ol>
    </section>
  );
}

interface StepItemProps {
  step: Step;
  isLast: boolean;
  isOpen: boolean;
  checkpoints: Checkpoint[];
  maxLatency: number;
  onToggle: (id: string) => void;
}

const StepItem = memo(function StepItem({
  step: s,
  isLast,
  isOpen,
  checkpoints,
  maxLatency,
  onToggle,
}: StepItemProps) {
  const hasDetails = stepHasDetails(s);
  const latencyPct =
    s.latency_ms != null && maxLatency > 0
      ? Math.max(2, (s.latency_ms / maxLatency) * 100)
      : 0;

  return (
    <li
      className="relative flex gap-3 pb-4 last:pb-0"
      style={{ contentVisibility: "auto", containIntrinsicSize: "0 120px" }}
    >
      <div className="flex flex-col items-center w-4 shrink-0">
        <span
          className={clsx(
            "size-3 rounded-full border-2 mt-1.5 z-10",
            statusDot[s.status],
          )}
          aria-hidden
        />
        {!isLast ? (
          <span
            className={clsx(
              "w-0.5 flex-1 mt-1 rounded-full",
              statusRail[s.status],
            )}
            aria-hidden
          />
        ) : null}
      </div>

      <div className="flex-1 min-w-0 rounded-lg border border-border bg-bg overflow-hidden">
        {latencyPct > 0 ? (
          <div className="h-0.5 bg-transparent" aria-hidden>
            <div
              className={clsx("h-full", statusBar[s.status])}
              style={{ width: `${latencyPct}%` }}
            />
          </div>
        ) : null}

        <div className="p-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted font-mono">#{s.index}</span>
            <span className="font-medium">{s.node}</span>
            <StatusBadge status={s.status} />
            {checkpoints.map((cp) => (
              <CheckpointMarker key={cp.id} checkpoint={cp} />
            ))}
            <span className="text-xs text-muted font-mono ml-auto tabular-nums">
              {formatRelativeTime(s.created_at)}
              {s.updated_at !== s.created_at
                ? ` → ${formatRelativeTime(s.updated_at)}`
                : ""}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs text-muted font-mono">
            <span title="Step latency">
              latency {formatLatency(s.latency_ms)}
            </span>
            {(s.tokens_in != null || s.tokens_out != null) && (
              <span>
                {s.tokens_in ?? 0}→{s.tokens_out ?? 0} tok
              </span>
            )}
            {s.cost_usd != null && (
              <span className="text-accent">{formatCostUsd(s.cost_usd)}</span>
            )}
            {s.tool_calls.length > 0 && (
              <span>
                {s.tool_calls.length} tool
                {s.tool_calls.length === 1 ? "" : "s"}
              </span>
            )}
          </div>

          {s.error ? (
            <div className="text-bad text-xs font-mono">{s.error}</div>
          ) : null}

          {hasDetails ? (
            <button
              type="button"
              className="text-xs text-accent hover:underline"
              onClick={() => onToggle(s.id)}
              aria-expanded={isOpen}
            >
              {isOpen ? "Hide details" : "Show details"}
            </button>
          ) : null}

          {isOpen ? <StepDetails step={s} /> : null}
        </div>
      </div>
    </li>
  );
});

function StepDetails({ step: s }: { step: Step }) {
  return (
    <div className="space-y-2 pt-1 border-t border-border">
      {Object.keys(s.input).length > 0 ? (
        <DetailBlock label="Input" value={s.input} />
      ) : null}
      {s.output ? <DetailBlock label="Output" value={s.output} /> : null}
      {s.tool_calls.length > 0 ? <ToolCallList calls={s.tool_calls} /> : null}
    </div>
  );
}

function ToolCallList({ calls }: { calls: ToolCall[] }) {
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted uppercase tracking-wide">Tool calls</div>
      <ul className="space-y-1.5 text-xs font-mono">
        {calls.map((c) => (
          <li
            key={c.id}
            className="rounded border border-border px-2 py-1.5 space-y-0.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-accent">{c.name}</span>
              {c.latency_ms != null && (
                <span className="text-muted">{formatLatency(c.latency_ms)}</span>
              )}
              {c.error ? (
                <span className="text-bad">error</span>
              ) : c.result ? (
                <span className="text-good">ok</span>
              ) : (
                <span className="text-muted">pending</span>
              )}
            </div>
            <JsonPreview label="args" value={c.arguments} />
            {c.result ? <JsonPreview label="result" value={c.result} /> : null}
            {c.error ? (
              <div className="text-bad">error: {c.error}</div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DetailBlock({
  label,
  value,
}: {
  label: string;
  value: Record<string, unknown>;
}) {
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
      <TruncatedPre text={text} />
    </div>
  );
}

function JsonPreview({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  const text = useMemo(
    () => `${label}: ${JSON.stringify(value)}`,
    [label, value],
  );
  return <TruncatedPre text={text} className="text-muted" />;
}

function TruncatedPre({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const needsTruncate = text.length > JSON_PREVIEW_CHARS;
  const visible =
    !needsTruncate || showAll ? text : `${text.slice(0, JSON_PREVIEW_CHARS)}…`;

  return (
    <div className="space-y-1">
      <pre
        className={clsx(
          "text-xs font-mono whitespace-pre-wrap break-all",
          className ?? "text-muted",
        )}
      >
        {visible}
      </pre>
      {needsTruncate ? (
        <button
          type="button"
          className="text-xs text-accent hover:underline"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll
            ? "Show less"
            : `Show all (${text.length.toLocaleString()} chars)`}
        </button>
      ) : null}
    </div>
  );
}
