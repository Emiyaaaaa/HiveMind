import type { RunUsage, Step } from "./types";

export function formatCostUsd(value: number): string {
  if (value === 0) return "$0.00";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatTokenCount(value: number): string {
  return value.toLocaleString();
}

export function normalizeUsage(usage: Partial<RunUsage> | null | undefined): RunUsage {
  return {
    tokens_in: usage?.tokens_in ?? 0,
    tokens_out: usage?.tokens_out ?? 0,
    cost_usd: usage?.cost_usd ?? 0,
    latency_ms: usage?.latency_ms ?? null,
    step_count: usage?.step_count ?? 0,
    failed_step_count: usage?.failed_step_count ?? 0,
    tool_call_count: usage?.tool_call_count ?? 0,
    failed_tool_call_count: usage?.failed_tool_call_count ?? 0,
  };
}

export function hasUsageMetrics(usage: RunUsage): boolean {
  return (
    usage.tokens_in > 0 ||
    usage.tokens_out > 0 ||
    usage.cost_usd > 0 ||
    usage.step_count > 0 ||
    usage.tool_call_count > 0
  );
}

export function stepHasMetrics(step: Step): boolean {
  return (
    (step.tokens_in ?? 0) > 0 ||
    (step.tokens_out ?? 0) > 0 ||
    (step.cost_usd ?? 0) > 0
  );
}
