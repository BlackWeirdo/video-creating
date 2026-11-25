const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

const SAFE_FORWARD_HEADERS = [
  "content-type",
  "accept",
  "range",
  "if-range",
  "authorization",
  "cookie",
  "last-event-id",
  "cache-control",
  "origin",
  "referer",
  "sec-fetch-site",
  "sec-fetch-mode",
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
  "www-authenticate",
  "location",
  "vary",
] as const;

type DuplexRequestInit = RequestInit & { duplex?: "half" };

function normalizeAuthority(rawHostOrUrl: string, defaultScheme: string): string {
  const trimmed = rawHostOrUrl.trim();
  if (!trimmed) return "";
  try {
    const parsed = trimmed.includes("://")
      ? new URL(trimmed)
      : new URL(`${defaultScheme}://${trimmed}`);
    const hostname = parsed.hostname.toLowerCase();
    if (!hostname) return "";
    const port = parsed.port || (parsed.protocol === "https:" ? "443" : "80");
    return hostname.includes(":") ? `[${hostname}]:${port}` : `${hostname}:${port}`;
  } catch {
    return "";
  }
}

export function checkProxyMutationCsrf(request: Request): string | null {
  const method = request.method.toUpperCase();
  if (SAFE_METHODS.has(method)) return null;

  const secFetchSite = (request.headers.get("sec-fetch-site") || "").trim().toLowerCase();
  if (secFetchSite && secFetchSite !== "same-origin" && secFetchSite !== "none") {
    return `Cross-origin request blocked at UI proxy (Sec-Fetch-Site=${secFetchSite})`;
  }

  const reqUrl = new URL(request.url);
  const scheme = reqUrl.protocol.replace(":", "") || "http";
  const hostHeader = (request.headers.get("host") || reqUrl.host || "").trim();
  const expectedAuthority = normalizeAuthority(hostHeader, scheme);

  const origin = (request.headers.get("origin") || "").trim();
  if (origin) {
    if (origin.toLowerCase() === "null") {
      return "Cross-origin request blocked at UI proxy (Origin=null)";
    }
    const originAuthority = normalizeAuthority(origin, scheme);
    if (!originAuthority || originAuthority !== expectedAuthority) {
      return "Cross-origin request blocked at UI proxy (Origin mismatch)";
    }
    return null;
  }

  if (!secFetchSite) {
    const referer = (request.headers.get("referer") || "").trim();
    if (referer) {
      const refAuthority = normalizeAuthority(referer, scheme);
      if (!refAuthority || refAuthority !== expectedAuthority) {
        return "Cross-origin request blocked at UI proxy (Referer mismatch)";
      }
    }
  }

  return null;
}

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
  const csrfError = checkProxyMutationCsrf(request);
  if (csrfError) {
    return new Response(csrfError, { status: 403 });
  }

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
