import type { RunUsage, Step } from "@/lib/types";
import {
  formatCostUsd,
  formatTokenCount,
  hasUsageMetrics,
  stepHasMetrics,
} from "@/lib/usage";

interface TokenCostSummaryProps {
  usage: RunUsage;
  steps?: Step[];
  compact?: boolean;
}

export function TokenCostSummary({
  usage,
  steps = [],
  compact = false,
}: TokenCostSummaryProps) {
  if (!hasUsageMetrics(usage)) {
    return (
      <p className="text-xs text-muted">
        No token or cost data yet (LLM steps record usage when the adapter reports
        it).
      </p>
    );
  }

  return (
    <div className={compact ? "space-y-2" : "space-y-4"}>
      <dl
        className={
          compact
            ? "grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm"
            : "grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm"
        }
      >
        <div>
          <dt className="text-xs text-muted uppercase tracking-wide">Tokens in</dt>
          <dd className="font-mono tabular-nums">
            {formatTokenCount(usage.tokens_in)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted uppercase tracking-wide">Tokens out</dt>
          <dd className="font-mono tabular-nums">
            {formatTokenCount(usage.tokens_out)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted uppercase tracking-wide">Est. cost</dt>
          <dd className="font-mono tabular-nums text-accent">
            {formatCostUsd(usage.cost_usd)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted uppercase tracking-wide">Latency</dt>
          <dd className="font-mono tabular-nums">
            {usage.latency_ms != null
              ? `${formatTokenCount(usage.latency_ms)} ms`
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted uppercase tracking-wide">Steps</dt>
          <dd className="font-mono tabular-nums">
            {formatTokenCount(usage.step_count)}
            {usage.failed_step_count > 0
              ? ` (${usage.failed_step_count} failed)`
              : ""}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted uppercase tracking-wide">
            Tool calls
          </dt>
          <dd className="font-mono tabular-nums">
            {formatTokenCount(usage.tool_call_count)}
            {usage.failed_tool_call_count > 0
              ? ` (${usage.failed_tool_call_count} failed)`
              : ""}
          </dd>
        </div>
      </dl>

      {!compact && steps.some(stepHasMetrics) ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border border-border rounded-lg overflow-hidden">
            <thead className="text-left text-muted bg-bg">
              <tr>
                <th className="px-3 py-2 font-medium">Step</th>
                <th className="px-3 py-2 font-medium">In</th>
                <th className="px-3 py-2 font-medium">Out</th>
                <th className="px-3 py-2 font-medium">Cost</th>
                <th className="px-3 py-2 font-medium">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border font-mono tabular-nums">
              {steps.filter(stepHasMetrics).map((s) => (
                <tr key={s.id}>
                  <td className="px-3 py-2">
                    <span className="text-muted">#{s.index}</span> {s.node}
                  </td>
                  <td className="px-3 py-2">{s.tokens_in ?? "—"}</td>
                  <td className="px-3 py-2">{s.tokens_out ?? "—"}</td>
                  <td className="px-3 py-2 text-accent">
                    {s.cost_usd != null ? formatCostUsd(s.cost_usd) : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {s.latency_ms != null ? `${s.latency_ms} ms` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
