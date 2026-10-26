"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { RunAuditEvent } from "@/lib/types";

interface Props {
  runId: string;
}

function detailSummary(event: RunAuditEvent): string | null {
  const detail = event.detail;
  const parts: string[] = [];
  if (typeof detail.checkpoint_index === "number") {
    parts.push(`CP #${detail.checkpoint_index}`);
  }
  const input = detail.input;
  if (input && typeof input === "object" && !Array.isArray(input)) {
    const record = input as Record<string, unknown>;
    const route =
      typeof record.route === "string"
        ? record.route
        : typeof record.approval === "string"
          ? record.approval
          : null;
    if (route) parts.push(route);
    if (typeof record.note === "string" && record.note.trim()) {
      parts.push(record.note.trim());
    }
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function ApprovalAudit({ runId }: Props) {
  const audit = useQuery({
    queryKey: ["run-audit", runId],
    queryFn: () => api.getRunAudit(runId),
  });

  if (audit.isLoading) return null;
  if (audit.error || !audit.data || audit.data.length === 0) return null;

  return (
    <section className="rounded-lg border border-border bg-surface p-4 space-y-3">
      <h2 className="font-medium">Approval &amp; cancel audit</h2>
      <ol className="space-y-2">
        {audit.data.map((event) => {
          const summary = detailSummary(event);
          return (
            <li
              key={event.id}
              className="flex items-start justify-between gap-3 rounded border border-border bg-bg px-3 py-2 text-sm"
            >
              <div className="min-w-0 space-y-0.5">
                <div className="font-mono text-xs uppercase tracking-wide">
                  {event.action}
                  {event.actor_role ? (
                    <span className="text-muted"> · {event.actor_role}</span>
                  ) : null}
                </div>
                <div className="text-xs text-muted truncate">
                  {event.actor_subject || "unknown actor"}
                  {summary ? ` · ${summary}` : ""}
                </div>
              </div>
              <span className="shrink-0 text-xs text-muted">
                {new Date(event.created_at).toLocaleString()}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
