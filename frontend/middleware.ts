import { NextResponse, type NextRequest } from "next/server";

/**
 * In demo mode, rewrite browser `/api/v1/*` calls (except SSE) to the
 * in-memory mock handlers under `/mock-api/v1/*`. SSE stays on
 * `/api/v1/events/[runId]` which branches on AGENTFLOW_MOCK itself.
 */
export function middleware(request: NextRequest) {
  const mock =
    process.env.AGENTFLOW_MOCK === "1" ||
    process.env.AGENTFLOW_MOCK === "true";
  if (!mock) return NextResponse.next();

  const { pathname } = request.nextUrl;
  if (!pathname.startsWith("/api/v1/")) return NextResponse.next();
  if (pathname.startsWith("/api/v1/events/")) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = pathname.replace(/^\/api\//, "/mock-api/");
  return NextResponse.rewrite(url);
}

export const config = {
  matcher: ["/api/v1/:path*"],
};
