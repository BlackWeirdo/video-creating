import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  ApiError,
  apiFetch,
  apiFetchBlob,
  isAbortError,
  parseApiResponse,
} from "../lib/api/client.ts";

describe("apiFetch & parseApiResponse", () => {
  it("preserves plain-text upstream error body without double-reading Response stream", async () => {
    await assert.rejects(
      () =>
        parseApiResponse(
          new Response("Bad Gateway Plaintext Error", { status: 502 })
        ),
      (err: unknown) =>
        err instanceof ApiError &&
        err.status === 502 &&
        err.message === "Bad Gateway Plaintext Error"
    );
  });

  it("extracts structured JSON detail message and status code", async () => {
    await assert.rejects(
      () =>
        parseApiResponse(
          new Response(JSON.stringify({ detail: "Workspace không tồn tại" }), {
            status: 404,
          })
        ),
      (err: unknown) =>
        err instanceof ApiError &&
        err.status === 404 &&
        err.message === "Workspace không tồn tại"
    );
  });

  it("handles 204 No Content and empty bodies without JSON parse failure", async () => {
    const res204 = await parseApiResponse(new Response(null, { status: 204 }));
    assert.equal(res204, undefined);

    const resEmpty = await parseApiResponse(new Response("   ", { status: 200 }));
    assert.equal(resEmpty, undefined);
  });

  it("apiFetchBlob returns Blob on 200 and throws ApiError on error status", async () => {
    const origFetch = globalThis.fetch;
    try {
      globalThis.fetch = async (input) => {
        const url = String(input);
        if (url.includes("fail")) {
          return new Response(
            JSON.stringify({ detail: "Mật khẩu tối thiểu 4 ký tự" }),
            { status: 400 }
          );
        }
        return new Response(new Uint8Array([1, 2, 3, 4]), { status: 200 });
      };

      const blob = await apiFetchBlob("/api/v1/backup/export", {
        method: "POST",
        body: JSON.stringify({ password: "abcd" }),
      });
      assert.equal(blob.size, 4);

      await assert.rejects(
        () =>
          apiFetchBlob("/api/v1/backup/export?fail=1", {
            method: "POST",
            body: JSON.stringify({ password: "a" }),
          }),
        (err: unknown) =>
          err instanceof ApiError &&
          err.status === 400 &&
          err.message === "Mật khẩu tối thiểu 4 ký tự"
      );
    } finally {
      globalThis.fetch = origFetch;
    }
  });

  it("forwards AbortSignal and recognizes AbortError", async () => {
    const ac = new AbortController();
    ac.abort();
    await assert.rejects(
      () => apiFetch("http://127.0.0.1:9/api/v1/dashboard", { signal: ac.signal }),
      (err: unknown) => isAbortError(err)
    );
  });
});
