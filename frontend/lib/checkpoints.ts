import type { Checkpoint, Step } from "./types";

/** Associate persisted checkpoints with the step they were saved after. */
export function checkpointsByStep(
  steps: Step[],
  checkpoints: Checkpoint[],
): Map<string, Checkpoint[]> {
  const byStepId = new Map<string, Checkpoint[]>();
  const unmatched: Checkpoint[] = [];

  for (const cp of checkpoints) {
    if (cp.label) {
      const step = steps.find((s) => s.node === cp.label);
      if (step) {
        const list = byStepId.get(step.id) ?? [];
        list.push(cp);
        byStepId.set(step.id, list);
        continue;
      }
    }
    unmatched.push(cp);
  }

  for (const cp of unmatched) {
    const cpTime = new Date(cp.created_at).getTime();
    let best: Step | null = null;
    let bestDelta = Infinity;
    for (const step of steps) {
      const stepTime = new Date(step.updated_at).getTime();
      const delta = cpTime - stepTime;
      if (delta >= 0 && delta < bestDelta) {
        best = step;
        bestDelta = delta;
      }
    }
    if (best) {
      const list = byStepId.get(best.id) ?? [];
      list.push(cp);
      byStepId.set(best.id, list);
    }
  }

  for (const [stepId, list] of byStepId) {
    list.sort((a, b) => a.index - b.index);
    byStepId.set(stepId, list);
  }

  return byStepId;
}

export function latestCheckpoint(
  checkpoints: Checkpoint[],
): Checkpoint | undefined {
  if (checkpoints.length === 0) return undefined;
  return checkpoints.reduce((a, b) => (a.index > b.index ? a : b));
}
