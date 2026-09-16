import type { Message, Run, RunStatus } from "./types";

export type ApprovalDecision = "approved" | "rejected";

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function isWaitingHuman(status: RunStatus): boolean {
  return status === "waiting_human";
}

export function waitingHumanRuns(runs: Run[] | undefined): Run[] {
  if (!runs) return [];
  return runs.filter((run) => run.status === "waiting_human");
}

export function approvalPrompt(
  output: Record<string, unknown> | null | undefined,
): string {
  if (!output) return "This run is waiting for human approval.";
  return (
    asString(output.awaiting) ??
    asString(output.prompt) ??
    "This run is waiting for human approval."
  );
}

export function approvalNode(
  output: Record<string, unknown> | null | undefined,
): string | null {
  if (!output) return null;
  return asString(output.node);
}

export function approvalDraft(
  output: Record<string, unknown> | null | undefined,
  messages: Message[] = [],
): string | null {
  const reply = output ? asString(output.reply) : null;
  if (reply) return reply;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message.role === "assistant" && message.content.trim()) {
      return message.content;
    }
  }
  return null;
}

export function runInputPrompt(
  input: Record<string, unknown> | null | undefined,
): string | null {
  if (!input) return null;
  return asString(input.prompt);
}

export function resumeInput(
  decision: ApprovalDecision,
  options?: { note?: string; extra?: Record<string, unknown> },
): Record<string, unknown> {
  const note = options?.note?.trim();
  return {
    ...(options?.extra ?? {}),
    route: decision,
    approval: decision,
    ...(note ? { note } : {}),
  };
}
