"use client";

import { useEffect, useRef, useState } from "react";

import { eventStreamUrl } from "@/lib/api";
import type { RunEvent } from "@/lib/types";

interface Props {
  runId: string;
  onTerminal?: () => void;
}

const TERMINAL = new Set(["run.completed", "run.failed", "run.cancelled"]);

function formatEventData(type: string, data: Record<string, unknown>): string {
  if (type === "checkpoint.created") {
    const label = data.label;
    const stateKeys =
      data.state && typeof data.state === "object"
        ? Object.keys(data.state as Record<string, unknown>).join(", ")
        : "";
    const parts = ["checkpoint saved"];
    if (label) parts.push(`label=${String(label)}`);
    if (stateKeys) parts.push(`state keys: ${stateKeys}`);
    return parts.join(" · ");
  }
  return JSON.stringify(data);
}

export function EventStream({ runId, onTerminal }: Props) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const url = eventStreamUrl(runId);
    const source = new EventSource(url);

    const onMessage = (event: MessageEvent) => {
      try {
        const data: RunEvent = JSON.parse(event.data);
        setEvents((prev) => [...prev, data]);
        if (TERMINAL.has(data.type)) {
          onTerminal?.();
          source.close();
        }
      } catch {
        // ignore malformed events
      }
    };

    const eventTypes = [
      "run.created",
      "run.started",
      "run.completed",
      "run.failed",
      "run.cancelled",
      "step.started",
      "step.updated",
      "step.completed",
      "step.failed",
      "token.delta",
      "message.created",
      "tool_call.started",
      "tool_call.completed",
      "checkpoint.created",
      "log",
    ];
    eventTypes.forEach((t) => source.addEventListener(t, onMessage));

    return () => {
      eventTypes.forEach((t) => source.removeEventListener(t, onMessage));
      source.close();
    };
  }, [runId, onTerminal]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="rounded border border-border bg-bg font-mono text-xs">
      <div className="px-3 py-2 border-b border-border text-muted">
        Live event stream · {events.length} events
      </div>
      <div className="max-h-80 overflow-y-auto p-3 space-y-1">
        {events.length === 0 ? (
          <div className="text-muted">Waiting for events…</div>
        ) : (
          events.map((e, i) => (
            <div key={i} className="flex gap-3">
              <span className="text-muted shrink-0">
                {new Date(e.at).toLocaleTimeString()}
              </span>
              <span
                className={
                  e.type === "checkpoint.created"
                    ? "text-warn shrink-0"
                    : "text-accent shrink-0"
                }
              >
                {e.type}
              </span>
              <span className="text-muted truncate">
                {formatEventData(e.type, e.data)}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
