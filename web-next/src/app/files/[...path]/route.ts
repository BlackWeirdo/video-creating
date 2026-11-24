import { encodeBackendSegments, proxyToBackend } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

async function handleFiles(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const sub = encodeBackendSegments(path);
  return proxyToBackend(request, sub ? `/files/${sub}` : "/files");
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  return handleFiles(request, context);
}

export async function HEAD(request: Request, context: RouteContext): Promise<Response> {
  return handleFiles(request, context);
}

export async function OPTIONS(request: Request, context: RouteContext): Promise<Response> {
  return handleFiles(request, context);
}
