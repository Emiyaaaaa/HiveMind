import clsx from "clsx";
import type { RunStatus } from "@/lib/types";

const palette: Record<RunStatus, string> = {
  pending: "bg-border text-muted",
  running: "bg-accent/20 text-accent",
  succeeded: "bg-good/20 text-good",
  failed: "bg-bad/20 text-bad",
  cancelled: "bg-border text-muted",
  waiting_human: "bg-warn/20 text-warn",
};

export function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <span
      className={clsx(
        "rounded px-2 py-0.5 text-xs font-mono uppercase tracking-wide",
        palette[status],
      )}
    >
      {status}
    </span>
  );
}
