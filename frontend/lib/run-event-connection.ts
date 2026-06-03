import { eventStreamUrl } from "./api";
import {
  isTerminalRunEvent,
  RUN_EVENT_TYPES,
} from "./run-events";
import type { RunEvent } from "./types";

export type RunEventConnectionStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "closed";

export interface StoredRunEvent extends RunEvent {
  clientSeq: number;
  eventId?: string;
}

export interface RunEventConnectionHandlers {
  onEvent?: (event: RunEvent, clientSeq: number, eventId?: string) => void;
  onTerminal?: (event: RunEvent) => void;
  onStatusChange?: (status: RunEventConnectionStatus) => void;
}

const INITIAL_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 30_000;

function streamUrl(runId: string, lastEventId: string | null): string {
  const base = eventStreamUrl(runId);
  if (!lastEventId) return base;
  const params = new URLSearchParams({ last_event_id: lastEventId });
  return `${base}?${params.toString()}`;
}

export function createRunEventConnection(
  runId: string,
  handlers: RunEventConnectionHandlers,
): { close: () => void } {
  let cancelled = false;
  let source: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempt = 0;
  let terminal = false;
  let clientSeq = 0;
  let lastEventId: string | null = null;

  const setStatus = (status: RunEventConnectionStatus) => {
    if (!cancelled) handlers.onStatusChange?.(status);
  };

  const clearReconnectTimer = () => {
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const closeSource = () => {
    if (!source) return;
    RUN_EVENT_TYPES.forEach((type) => source!.removeEventListener(type, onMessage));
    source.close();
    source = null;
  };

  const finishTerminal = (event: RunEvent) => {
    terminal = true;
    clearReconnectTimer();
    closeSource();
    setStatus("closed");
    handlers.onTerminal?.(event);
  };

  const scheduleReconnect = () => {
    if (cancelled || terminal) return;
    setStatus("reconnecting");
    const delay = Math.min(
      INITIAL_RECONNECT_MS * 2 ** reconnectAttempt,
      MAX_RECONNECT_MS,
    );
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  const onMessage = (event: MessageEvent) => {
    if (cancelled || terminal) return;
    if (event.lastEventId) {
      lastEventId = event.lastEventId;
    }
    try {
      const data: RunEvent = JSON.parse(event.data);
      clientSeq += 1;
      handlers.onEvent?.(data, clientSeq, event.lastEventId || undefined);
      if (isTerminalRunEvent(data.type)) {
        finishTerminal(data);
      }
    } catch {
      // ignore malformed events
    }
  };

  const connect = () => {
    if (cancelled || terminal) return;

    closeSource();
    setStatus(reconnectAttempt === 0 ? "connecting" : "reconnecting");

    const next = new EventSource(streamUrl(runId, lastEventId));
    source = next;

    next.addEventListener("open", () => {
      if (cancelled || terminal) return;
      reconnectAttempt = 0;
      setStatus("connected");
    });

    RUN_EVENT_TYPES.forEach((type) => next.addEventListener(type, onMessage));

    next.onerror = () => {
      if (cancelled || terminal) return;
      closeSource();
      scheduleReconnect();
    };
  };

  connect();

  return {
    close: () => {
      cancelled = true;
      clearReconnectTimer();
      closeSource();
    },
  };
}

export function connectionLabel(status: RunEventConnectionStatus): string {
  switch (status) {
    case "connecting":
      return "connecting…";
    case "connected":
      return "live";
    case "reconnecting":
      return "reconnecting…";
    case "closed":
      return "closed";
  }
}
