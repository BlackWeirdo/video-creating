"""Live PoC benchmark runner for `vc-hardened` Muse Gateway (2 accounts, 10 parallel 8s 9:16 video tasks).

Usage (against a running hardened Muse Gateway with >=2 Muse accounts signed in):
    .venv\\Scripts\\python.exe scripts\\benchmark_muse_gateway_poc.py --base-url http://127.0.0.1:1412 --api-key <KEY> --count 10 --duration 8
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from videocreator.config_ai import MuseGatewayConfig
from videocreator.muse_gateway.client import MuseGatewayClient


def _run_one_video(client: MuseGatewayClient, idx: int, duration_s: int, timeout_s: float) -> dict[str, Any]:
    t0 = time.monotonic()
    created = client.create_task(
        {
            "model": "muse-video",
            "prompt": f"Cận cảnh ánh sáng studio sang trọng chuyển động chậm trên nền đá đen #{idx + 1}",
            "duration": duration_s,
            "ratio": "9:16",
            "idempotency_key": f"poc-bench-{int(t0)}-{idx}",
        }
    )
    tid = str(created["id"])
    deadline = t0 + timeout_s
    while time.monotonic() < deadline:
        time.sleep(8.0)
        cur = client.get_task(tid)
        st = str(cur.get("status") or "")
        if st in ("succeeded", "failed", "cancelled"):
            elapsed = round(time.monotonic() - t0, 2)
            return {
                "idx": idx,
                "task_id": tid,
                "status": st,
                "partial": bool(cur.get("partial")),
                "duration_sec": cur.get("duration_sec"),
                "elapsed_s": elapsed,
                "error": cur.get("error"),
            }
    return {
        "idx": idx,
        "task_id": tid,
        "status": "timeout",
        "partial": False,
        "duration_sec": None,
        "elapsed_s": round(time.monotonic() - t0, 2),
        "error": f"Timed out after {timeout_s}s",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark vc-hardened Muse Gateway multi-lane video generation")
    parser.add_argument("--base-url", default="http://127.0.0.1:1412")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--duration", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--out-json", default="")
    args = parser.parse_args(argv)

    cfg = MuseGatewayConfig(enabled=True, mode="local_sidecar", base_url=args.base_url)
    client = MuseGatewayClient(cfg, api_key_override=args.api_key)
    safety = client.verify_ready_and_safe()
    print(f"[OK] Verified hardened Muse Gateway: {safety}")

    n = max(1, int(args.count))
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(16, n)) as pool:
        results = list(
            pool.map(lambda i: _run_one_video(client, i, args.duration, args.timeout), range(n))
        )
    wall_s = round(time.monotonic() - t_start, 2)

    ok_rows = [r for r in results if r["status"] == "succeeded"]
    partial_rows = [r for r in ok_rows if r["partial"]]
    latencies = sorted(float(r["elapsed_s"]) for r in ok_rows)
    success_rate = round((len(ok_rows) / n) * 100.0, 1)
    summary = {
        "total_tasks": n,
        "succeeded": len(ok_rows),
        "failed": n - len(ok_rows),
        "partial_count": len(partial_rows),
        "success_rate_pct": success_rate,
        "wall_clock_s": wall_s,
        "p50_s": round(statistics.median(latencies), 2) if latencies else None,
        "p95_s": round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 2) if latencies else None,
        "gate_passed": success_rate >= 80.0,
        "tasks": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if summary["gate_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
