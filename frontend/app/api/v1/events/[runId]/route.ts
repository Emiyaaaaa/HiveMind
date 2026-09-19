import { type NextRequest } from "next/server";

import { isMockEnabled } from "@/lib/mock/enabled";
import { streamMockRunEvents } from "@/lib/mock/sse";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const backend = process.env.AGENTFLOW_API_URL || "http://localhost:8000";

/**
 * Stream SSE from the API without Next.js rewrite buffering.
 * Route handlers take precedence over `rewrites()` in next.config.mjs.
 * In demo mode (`AGENTFLOW_MOCK=1`) events are served from the in-memory mock.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;

  if (isMockEnabled()) {
    return streamMockRunEvents(runId, request);
  }

  const url = new URL(`${backend}/v1/events/${runId}`);
  request.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.set(key, value);
  });

  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Cache-Control": "no-cache",
  };
  const lastEventId = request.headers.get("last-event-id");
  if (lastEventId) {
    headers["Last-Event-ID"] = lastEventId;
  }
  const apiKey =
    process.env.AGENTFLOW_API_KEY || process.env.NEXT_PUBLIC_AGENTFLOW_API_KEY;
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }

  const upstream = await fetch(url.toString(), {
    headers,
    cache: "no-store",
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
