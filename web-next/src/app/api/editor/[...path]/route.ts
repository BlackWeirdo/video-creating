import { encodeBackendSegments, proxyToBackend } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

async function handleEditorApi(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const sub = encodeBackendSegments(path);
  return proxyToBackend(request, sub ? `/api/editor/${sub}` : "/api/editor");
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  return handleEditorApi(request, context);
}

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  return handleEditorApi(request, context);
}

export async function PUT(request: Request, context: RouteContext): Promise<Response> {
  return handleEditorApi(request, context);
}
