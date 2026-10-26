import type {
  RunEvent,
  RunEventSubscription,
  SubscribeRunEventsOptions,
} from "./types.js";

const TERMINAL_EVENT_TYPES = new Set([
  "run.completed",
  "run.failed",
  "run.cancelled",
]);

function streamUrl(baseUrl: string, runId: string, lastEventId?: string | null): string {
  const url = new URL(`${baseUrl.replace(/\/$/, "")}/v1/events/${runId}`);
  if (lastEventId) {
    url.searchParams.set("last_event_id", lastEventId);
  }
  return url.toString();
}

/** Browser-first SSE helper; uses EventSource when available. */
export function subscribeRunEvents(
  baseUrl: string,
  runId: string,
  options: SubscribeRunEventsOptions = {},
): RunEventSubscription {
  if (typeof EventSource === "undefined") {
    throw new Error(
      "subscribeRunEvents requires EventSource (browser). Use fetch-based streaming in Node.",
    );
  }

  let closed = false;
  let lastEventId = options.lastEventId ?? null;
  let source: EventSource | null = null;

  const connect = () => {
    if (closed) return;
    source?.close();
    source = new EventSource(streamUrl(baseUrl, runId, lastEventId));
    source.onmessage = (message) => {
      if (closed) return;
      if (message.lastEventId) {
        lastEventId = message.lastEventId;
      }
      try {
        const event = JSON.parse(message.data) as RunEvent;
        options.onEvent?.(event, message.lastEventId || undefined);
        if (TERMINAL_EVENT_TYPES.has(event.type)) {
          close();
        }
      } catch {
        // ignore malformed frames
      }
    };
    source.onerror = () => {
      if (closed) return;
      source?.close();
      source = null;
      window.setTimeout(connect, 1_000);
    };
  };

  const close = () => {
    closed = true;
    source?.close();
    source = null;
  };

  connect();
  return { close };
}
