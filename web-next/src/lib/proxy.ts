const SAFE_FORWARD_HEADERS = [
  "content-type",
  "accept",
  "range",
  "if-range",
  "authorization",
  "cookie",
  "last-event-id",
  "cache-control",
] as const;

const SAFE_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "content-range",
  "accept-ranges",
  "content-length",
  "cache-control",
  "etag",
  "last-modified",
] as const;

type DuplexRequestInit = RequestInit & { duplex?: "half" };

export function resolveBackendBaseUrl(): string {
  return (process.env.VIDEOCREATOR_API_URL || "http://127.0.0.1:8765").replace(/\/+$/, "");
}

export function encodeBackendSegments(segments: string[] | undefined): string {
  if (!segments || segments.length === 0) return "";
  return segments.map((seg) => encodeURIComponent(seg)).join("/");
}

export async function proxyToBackend(
  request: Request,
  backendPath: string
): Promise<Response> {
  const base = resolveBackendBaseUrl();
  const normalizedPath = backendPath.startsWith("/") ? backendPath : `/${backendPath}`;
  const search = new URL(request.url).search;
  const targetUrl = `${base}${normalizedPath}${search}`;

  const headers = new Headers();
  for (const name of SAFE_FORWARD_HEADERS) {
    const val = request.headers.get(name);
    if (val !== null) {
      headers.set(name, val);
    }
  }
  headers.set("accept-encoding", "identity");

  const method = request.method.toUpperCase();
  const init: DuplexRequestInit = {
    method,
    headers,
    cache: "no-store",
    redirect: "manual",
  };
  if (method !== "GET" && method !== "HEAD" && request.body !== null) {
    init.body = request.body;
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl, init);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unavailable";
    return Response.json(
      { detail: `FastAPI backend unavailable at ${base}: ${message}` },
      { status: 502 }
    );
  }

  const outHeaders = new Headers();
  for (const name of SAFE_RESPONSE_HEADERS) {
    const val = upstream.headers.get(name);
    if (val !== null) {
      outHeaders.set(name, val);
    }
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: outHeaders,
  });
}
