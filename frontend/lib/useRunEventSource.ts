"use client";

import { useEffect, useRef, useState } from "react";

import {
  connectionLabel,
  createRunEventConnection,
  type RunEventConnectionStatus,
  type StoredRunEvent,
} from "@/lib/run-event-connection";
import type { RunEvent } from "@/lib/types";

export { connectionLabel };
export type { RunEventConnectionStatus, StoredRunEvent };

interface UseRunEventSourceOptions {
  runId: string;
  enabled?: boolean;
  onEvent?: (event: RunEvent) => void;
  onTerminal?: (event: RunEvent) => void;
}

export function useRunEventSource({
  runId,
  enabled = true,
  onEvent,
  onTerminal,
}: UseRunEventSourceOptions) {
  const [events, setEvents] = useState<StoredRunEvent[]>([]);
  const [status, setStatus] = useState<RunEventConnectionStatus>(
    enabled ? "connecting" : "closed",
  );
  const onEventRef = useRef(onEvent);
  const onTerminalRef = useRef(onTerminal);

  onEventRef.current = onEvent;
  onTerminalRef.current = onTerminal;

  useEffect(() => {
    if (!enabled) {
      setStatus("closed");
      return;
    }

    setEvents([]);
    setStatus("connecting");

    const connection = createRunEventConnection(runId, {
      onStatusChange: setStatus,
      onEvent: (event, clientSeq) => {
        setEvents((prev) => [...prev, { ...event, clientSeq }]);
        onEventRef.current?.(event);
      },
      onTerminal: (event) => {
        onTerminalRef.current?.(event);
      },
    });

    return () => connection.close();
  }, [runId, enabled]);

  return { events, status };
}

interface UseMultiRunEventSourceOptions {
  runIds: string[];
  onEvent?: (event: RunEvent) => void;
  onTerminal?: (event: RunEvent) => void;
}

export function useMultiRunEventSource({
  runIds,
  onEvent,
  onTerminal,
}: UseMultiRunEventSourceOptions) {
  const onEventRef = useRef(onEvent);
  const onTerminalRef = useRef(onTerminal);

  onEventRef.current = onEvent;
  onTerminalRef.current = onTerminal;

  const runKey = runIds.slice().sort().join(",");

  useEffect(() => {
    if (!runKey) return;

    const ids = runKey.split(",");
    const connections = ids.map((runId) =>
      createRunEventConnection(runId, {
        onEvent: (event) => {
          onEventRef.current?.(event);
        },
        onTerminal: (event) => {
          onTerminalRef.current?.(event);
        },
      }),
    );

    return () => {
      connections.forEach((connection) => connection.close());
    };
  }, [runKey]);
}
