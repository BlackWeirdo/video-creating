import { encodeBackendSegments, proxyToBackend } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const sub = encodeBackendSegments(path);
  return proxyToBackend(request, sub ? `/assets/${sub}` : "/assets");
}
