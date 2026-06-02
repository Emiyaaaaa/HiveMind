import type { RunUsage, Step } from "./types";

export function formatCostUsd(value: number): string {
  if (value === 0) return "$0.00";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatTokenCount(value: number): string {
  return value.toLocaleString();
}

export function hasUsageMetrics(usage: RunUsage): boolean {
  return usage.tokens_in > 0 || usage.tokens_out > 0 || usage.cost_usd > 0;
}

export function stepHasMetrics(step: Step): boolean {
  return (
    (step.tokens_in ?? 0) > 0 ||
    (step.tokens_out ?? 0) > 0 ||
    (step.cost_usd ?? 0) > 0
  );
}
