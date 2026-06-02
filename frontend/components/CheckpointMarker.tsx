import type { Checkpoint } from "@/lib/types";

interface Props {
  checkpoint: Checkpoint;
  compact?: boolean;
}

export function CheckpointMarker({ checkpoint, compact = false }: Props) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-warn/15 text-warn px-2 py-0.5 text-xs font-mono"
      title={`Checkpoint #${checkpoint.index} saved at ${new Date(checkpoint.created_at).toLocaleString()}`}
    >
      <span aria-hidden>◆</span>
      {compact ? `#${checkpoint.index}` : `CP #${checkpoint.index}`}
      {checkpoint.label ? (
        <span className="text-warn/80">· {checkpoint.label}</span>
      ) : null}
    </span>
  );
}
