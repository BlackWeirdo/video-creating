import { encodeBackendSegments, proxyToBackend } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

async function handleApiV1(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const sub = encodeBackendSegments(path);
  return proxyToBackend(request, sub ? `/api/v1/${sub}` : "/api/v1");
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  return handleApiV1(request, context);
}

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  return handleApiV1(request, context);
}

export async function PUT(request: Request, context: RouteContext): Promise<Response> {
  return handleApiV1(request, context);
}

export async function PATCH(request: Request, context: RouteContext): Promise<Response> {
  return handleApiV1(request, context);
}

export async function DELETE(request: Request, context: RouteContext): Promise<Response> {
  return handleApiV1(request, context);
}

export async function HEAD(request: Request, context: RouteContext): Promise<Response> {
  return handleApiV1(request, context);
}

export async function OPTIONS(request: Request, context: RouteContext): Promise<Response> {
  return handleApiV1(request, context);
}
