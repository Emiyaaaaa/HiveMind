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
  /** Fires when a reconnect attempt succeeds (not the initial connect). */
  onReconnected?: () => void;
}

const INITIAL_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 30_000;
const CONNECT_TIMEOUT_MS = 30_000;
const WATCHDOG_INTERVAL_MS = 5_000;
/** Server heartbeat is 15s; allow several missed pings through proxies. */
const IDLE_TIMEOUT_MS = 60_000;

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
  let watchdogTimer: ReturnType<typeof setInterval> | null = null;
  let reconnectAttempt = 0;
  let terminal = false;
  let clientSeq = 0;
  let lastEventId: string | null = null;
  let connectStartedAt = 0;
  let lastActivityAt = 0;

  const setStatus = (status: RunEventConnectionStatus) => {
    if (!cancelled) handlers.onStatusChange?.(status);
  };

  const clearReconnectTimer = () => {
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const stopWatchdog = () => {
    if (watchdogTimer != null) {
      clearInterval(watchdogTimer);
      watchdogTimer = null;
    }
  };

  const bumpActivity = () => {
    lastActivityAt = Date.now();
  };

  const closeSource = () => {
    if (!source) return;
    RUN_EVENT_TYPES.forEach((type) => source!.removeEventListener(type, onMessage));
    source.removeEventListener("ping", onPing);
    source.onerror = null;
    source.close();
    source = null;
  };

  const finishTerminal = (event: RunEvent) => {
    terminal = true;
    clearReconnectTimer();
    stopWatchdog();
    closeSource();
    setStatus("closed");
    handlers.onTerminal?.(event);
  };

  const startWatchdog = () => {
    stopWatchdog();
    watchdogTimer = setInterval(() => {
      if (cancelled || terminal) return;

      const now = Date.now();
      const state = source?.readyState;

      if (
        state === EventSource.CONNECTING &&
        connectStartedAt > 0 &&
        now - connectStartedAt > CONNECT_TIMEOUT_MS
      ) {
        closeSource();
        scheduleReconnect();
        return;
      }

      if (state === EventSource.OPEN && now - lastActivityAt > IDLE_TIMEOUT_MS) {
        closeSource();
        scheduleReconnect();
      }
    }, WATCHDOG_INTERVAL_MS);
  };

  const connect = () => {
    if (cancelled || terminal) return;

    const isReconnect = reconnectAttempt > 0;

    clearReconnectTimer();
    closeSource();
    setStatus(isReconnect ? "reconnecting" : "connecting");

    connectStartedAt = Date.now();
    bumpActivity();

    const next = new EventSource(streamUrl(runId, lastEventId));
    source = next;

    next.addEventListener("open", () => {
      if (cancelled || terminal) return;
      bumpActivity();
      reconnectAttempt = 0;
      setStatus("connected");
      if (isReconnect) {
        handlers.onReconnected?.();
      }
    });

    RUN_EVENT_TYPES.forEach((type) => next.addEventListener(type, onMessage));
    next.addEventListener("ping", onPing);

    next.onerror = () => {
      if (cancelled || terminal) return;
      // Close proactively so the browser does not auto-reconnect with a stale URL.
      if (source !== next) return;
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

  const onPing = () => {
    if (cancelled || terminal) return;
    bumpActivity();
    reconnectAttempt = 0;
  };

  const onMessage = (event: MessageEvent) => {
    if (cancelled || terminal) return;

    bumpActivity();

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

  startWatchdog();
  connect();

  return {
    close: () => {
      cancelled = true;
      clearReconnectTimer();
      stopWatchdog();
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
