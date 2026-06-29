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
  onReconnected?: () => void;
}

export function useRunEventSource({
  runId,
  enabled = true,
  onEvent,
  onTerminal,
  onReconnected,
}: UseRunEventSourceOptions) {
  const [events, setEvents] = useState<StoredRunEvent[]>([]);
  const [status, setStatus] = useState<RunEventConnectionStatus>(
    enabled ? "connecting" : "closed",
  );
  const onEventRef = useRef(onEvent);
  const onTerminalRef = useRef(onTerminal);
  const onReconnectedRef = useRef(onReconnected);

  onEventRef.current = onEvent;
  onTerminalRef.current = onTerminal;
  onReconnectedRef.current = onReconnected;

  useEffect(() => {
    if (!enabled) {
      setStatus("closed");
      return;
    }

    setEvents([]);
    setStatus("connecting");

    const connection = createRunEventConnection(runId, {
      onStatusChange: setStatus,
      onEvent: (event, clientSeq, eventId) => {
        setEvents((prev) => [...prev, { ...event, clientSeq, eventId }]);
        onEventRef.current?.(event);
      },
      onTerminal: (event) => {
        onTerminalRef.current?.(event);
      },
      onReconnected: () => {
        onReconnectedRef.current?.();
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
  onReconnected?: (runId: string) => void;
}

export function useMultiRunEventSource({
  runIds,
  onEvent,
  onTerminal,
  onReconnected,
}: UseMultiRunEventSourceOptions) {
  const onEventRef = useRef(onEvent);
  const onTerminalRef = useRef(onTerminal);
  const onReconnectedRef = useRef(onReconnected);

  onEventRef.current = onEvent;
  onTerminalRef.current = onTerminal;
  onReconnectedRef.current = onReconnected;

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
        onReconnected: () => {
          onReconnectedRef.current?.(runId);
        },
      }),
    );

    return () => {
      connections.forEach((connection) => connection.close());
    };
  }, [runKey]);
}
