import { type NextRequest } from "next/server";

import { handleMockApi } from "@/lib/mock/handler";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function dispatch(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> },
) {
  const { path = [] } = await context.params;
  return handleMockApi(request, path);
}

export const GET = dispatch;
export const POST = dispatch;
export const PUT = dispatch;
export const PATCH = dispatch;
export const DELETE = dispatch;
