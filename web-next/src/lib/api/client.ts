export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function isAbortError(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "name" in err &&
    (err as { name?: unknown }).name === "AbortError"
  );
}

export async function parseApiResponse<T = unknown>(res: Response): Promise<T> {
  const rawText = await res.text();
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    let detail: unknown = rawText;
    if (rawText) {
      try {
        const errBody = JSON.parse(rawText) as { detail?: unknown };
        if (errBody && errBody.detail !== undefined) {
          detail = errBody.detail;
          msg =
            typeof errBody.detail === "string"
              ? errBody.detail
              : JSON.stringify(errBody.detail);
        } else {
          msg = rawText.slice(0, 200);
        }
      } catch {
        msg = rawText.slice(0, 200);
      }
    }
    throw new ApiError(res.status, msg, detail);
  }

  if (res.status === 204 || !rawText.trim()) {
    return undefined as T;
  }
  return JSON.parse(rawText) as T;
}

function buildRequestHeaders(options?: RequestInit): Record<string, string> {
  const isFormData =
    typeof FormData !== "undefined" && options?.body instanceof FormData;
  const headers: Record<string, string> = isFormData
    ? {}
    : { "Content-Type": "application/json" };

  if (options?.headers) {
    Object.assign(headers, options.headers as Record<string, string>);
  }
  return headers;
}

export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: buildRequestHeaders(options),
    cache: "no-store",
  });

  return parseApiResponse<T>(res);
}

export async function apiFetchBlob(
  path: string,
  options?: RequestInit
): Promise<Blob> {
  const res = await fetch(path, {
    ...options,
    headers: buildRequestHeaders(options),
    cache: "no-store",
  });

  if (!res.ok) {
    await parseApiResponse<never>(res);
  }
  return res.blob();
}
