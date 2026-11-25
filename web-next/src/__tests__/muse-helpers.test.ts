import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  estimateParallelCapacity,
  formatMuseTaskStatus,
  mapMuseErrorToVi,
} from "../lib/muse-helpers.ts";

describe("muse-helpers", () => {
  it("computes parallel capacity bounded by maxParallel and rendersPerAccount", () => {
    assert.equal(estimateParallelCapacity(0, 2, 8), 0);
    assert.equal(estimateParallelCapacity(2, 2, 8), 4);
    assert.equal(estimateParallelCapacity(6, 2, 8), 8);
  });

  it("formats Muse task statuses and partial flag accurately", () => {
    assert.deepEqual(formatMuseTaskStatus("submitted"), {
      label: "Đang render Muse",
      tone: "cluster",
    });
    assert.deepEqual(formatMuseTaskStatus("succeeded", false), {
      label: "Hoàn tất",
      tone: "emerald",
    });
    assert.deepEqual(formatMuseTaskStatus("succeeded", true), {
      label: "Hoàn tất (dừng sớm)",
      tone: "amber",
    });
    assert.deepEqual(formatMuseTaskStatus("waiting_quota"), {
      label: "Chờ hồi hạn mức",
      tone: "amber",
    });
  });

  it("maps security, auth, quota and restart errors to clear Vietnamese guidance", () => {
    assert.match(mapMuseErrorToVi("cmdMode != off"), /vc-hardened/);
    assert.match(mapMuseErrorToVi("HTTP 401 unauthorized"), /Kết nối 1 chạm/);
    assert.match(mapMuseErrorToVi("Account hit quota limit"), /cooldown/);
    assert.match(mapMuseErrorToVi("Gateway restarted while running"), /thử lại/);
  });
});
