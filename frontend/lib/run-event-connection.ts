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

/** Mirrors backend `_is_after` — numeric IDs when possible, else lexicographic. */
function isEventIdAfter(entryId: string, afterId: string): boolean {
  const entryNum = Number(entryId);
  const afterNum = Number(afterId);
  if (!Number.isNaN(entryNum) && !Number.isNaN(afterNum)) {
    return entryNum > afterNum;
  }
  return entryId > afterId;
}

function reconnectDelayMs(attempt: number): number {
  const capped = Math.min(INITIAL_RECONNECT_MS * 2 ** attempt, MAX_RECONNECT_MS);
  // Equal jitter: spread retries without thundering herd.
  return Math.floor(capped / 2 + Math.random() * (capped / 2));
}

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
    source.onerror = null;
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

  const connect = () => {
    if (cancelled || terminal) return;

    clearReconnectTimer();
    closeSource();
    setStatus(reconnectAttempt === 0 ? "connecting" : "reconnecting");

    const next = new EventSource(streamUrl(runId, lastEventId));
    source = next;

    next.addEventListener("open", () => {
      if (cancelled || terminal) return;
      setStatus("connected");
    });

    RUN_EVENT_TYPES.forEach((type) => next.addEventListener(type, onMessage));

    next.onerror = () => {
      if (cancelled || terminal) return;
      // EventSource may fire onerror while still CONNECTING; only retry once closed.
      if (next.readyState !== EventSource.CLOSED) return;
      closeSource();
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (cancelled || terminal || reconnectTimer != null) return;
    setStatus("reconnecting");
    const delay = reconnectDelayMs(reconnectAttempt);
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  const reconnectNow = () => {
    if (cancelled || terminal) return;
    if (source?.readyState === EventSource.OPEN) return;
    reconnectAttempt = 0;
    connect();
  };

  const onVisibilityChange = () => {
    if (document.visibilityState === "visible") {
      reconnectNow();
    }
  };

  const onOnline = () => {
    reconnectNow();
  };

  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibilityChange);
  }
  if (typeof window !== "undefined") {
    window.addEventListener("online", onOnline);
  }

  const onMessage = (event: MessageEvent) => {
    if (cancelled || terminal) return;

    const incomingId = event.lastEventId;
    if (incomingId) {
      if (lastEventId && !isEventIdAfter(incomingId, lastEventId)) {
        return;
      }
      lastEventId = incomingId;
    }

    try {
      const data: RunEvent = JSON.parse(event.data);
      reconnectAttempt = 0;
      clientSeq += 1;
      handlers.onEvent?.(data, clientSeq, incomingId || undefined);
      if (isTerminalRunEvent(data.type)) {
        finishTerminal(data);
      }
    } catch {
      // ignore malformed events
    }
  };

  connect();

  return {
    close: () => {
      cancelled = true;
      clearReconnectTimer();
      closeSource();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      }
      if (typeof window !== "undefined") {
        window.removeEventListener("online", onOnline);
      }
      setStatus("closed");
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
