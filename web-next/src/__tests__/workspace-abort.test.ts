import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createAbortableQueryRunner } from "../lib/api/query-controller.ts";

describe("createAbortableQueryRunner (Workspace switch AbortController guard)", () => {
  it("aborts in-flight Workspace 1 query and prevents stale overwrite when switching to Workspace 2", async () => {
    const runner = createAbortableQueryRunner();
    const committed: string[] = [];
    const errors: string[] = [];
    let settledCount = 0;

    let signalWs1: AbortSignal | null = null;
    let resolveWs1!: (val: string) => void;

    // Start slow Workspace 1 request
    const p1 = runner.run(
      (sig) => {
        signalWs1 = sig;
        return new Promise<string>((resolve) => {
          resolveWs1 = resolve;
        });
      },
      {
        onSuccess: (d) => committed.push(d),
        onError: (e) => errors.push(e),
        onSettledLatest: () => {
          settledCount += 1;
        },
      }
    );

    // Immediately switch to Workspace 2 before Workspace 1 finishes
    const p2 = runner.run(
      async (sig) => {
        assert.equal(sig.aborted, false);
        return "workspace-2-fresh-data";
      },
      {
        onSuccess: (d) => committed.push(d),
        onError: (e) => errors.push(e),
        onSettledLatest: () => {
          settledCount += 1;
        },
      }
    );

    assert.ok(signalWs1 !== null && (signalWs1 as AbortSignal).aborted === true);

    await p2;
    // Now slow Workspace 1 resolves AFTER Workspace 2 already rendered
    resolveWs1("workspace-1-stale-data");
    await p1;

    assert.deepEqual(committed, ["workspace-2-fresh-data"]);
    assert.deepEqual(errors, []);
    assert.equal(settledCount, 1);
  });

  it("ignores stale errors from aborted Workspace 1 query", async () => {
    const runner = createAbortableQueryRunner();
    const errors: string[] = [];
    let rejectWs1!: (err: Error) => void;

    const p1 = runner.run(
      () =>
        new Promise<string>((_res, rej) => {
          rejectWs1 = rej;
        }),
      {
        onSuccess: () => {},
        onError: (e) => errors.push(e),
        onSettledLatest: () => {},
      }
    );

    const p2 = runner.run(
      async () => "ws2-ok",
      {
        onSuccess: () => {},
        onError: (e) => errors.push(e),
        onSettledLatest: () => {},
      }
    );

    await p2;
    rejectWs1(new Error("Stale network failure on WS1"));
    await p1;

    assert.deepEqual(errors, []);
  });
});
