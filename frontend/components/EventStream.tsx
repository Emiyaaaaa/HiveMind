"use client";

import { useEffect, useRef } from "react";

import {
  connectionLabel,
  type RunEventConnectionStatus,
  type StoredRunEvent,
} from "@/lib/run-event-connection";

interface Props {
  events: StoredRunEvent[];
  status: RunEventConnectionStatus;
}

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

export function EventStream({ events, status }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="rounded border border-border bg-bg font-mono text-xs">
      <div className="px-3 py-2 border-b border-border text-muted flex items-center justify-between gap-3">
        <span>Live event stream · {events.length} events</span>
        <span
          className={
            status === "connected"
              ? "text-good"
              : status === "closed"
                ? "text-muted"
                : "text-warn"
          }
        >
          {connectionLabel(status)}
        </span>
      </div>
      <div className="max-h-80 overflow-y-auto p-3 space-y-1">
        {events.length === 0 ? (
          <div className="text-muted">
            {status === "reconnecting"
              ? "Connection lost — retrying…"
              : status === "closed"
                ? "Stream closed"
                : "Waiting for events…"}
          </div>
        ) : (
          events.map((event) => (
            <EventStreamRow key={event.clientSeq} event={event} />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function EventStreamRow({ event }: { event: StoredRunEvent }) {
  return (
    <div className="flex gap-3">
      <span className="text-muted shrink-0">
        {new Date(event.at).toLocaleTimeString()}
      </span>
      <span
        className={
          event.type === "checkpoint.created"
            ? "text-warn shrink-0"
            : "text-accent shrink-0"
        }
      >
        {event.type}
      </span>
      <span className="text-muted truncate">
        {formatEventData(event.type, event.data)}
      </span>
    </div>
  );
}
