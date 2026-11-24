import { encodeBackendSegments, proxyToBackend } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

async function handleFreeCut(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const sub = encodeBackendSegments(path);
  return proxyToBackend(request, sub ? `/freecut/${sub}` : "/freecut");
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  return handleFreeCut(request, context);
}

export async function HEAD(request: Request, context: RouteContext): Promise<Response> {
  return handleFreeCut(request, context);
}
