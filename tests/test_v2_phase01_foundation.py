"""Real SQLite + Dual-Lane JobWorker + FastAPI /api/v1 tests for V2 Phase 01 (no mocks)."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import migrate, query_all, query_one
from videocreator.job_store import (
    get_queue_summary,
    is_queue_paused,
    update_job_progress,
)
from videocreator.jobs import (
    JobRegistry,
    JobWorker,
    classify_job_lane,
    enqueue_job,
    get_job,
)
from videocreator.products import create_product, list_products
from videocreator.workspaces import (
    DEFAULT_WORKSPACE_ID,
    archive_workspace,
    create_workspace,
    get_active_workspace_id,
    get_workspace,
    list_workspaces,
    require_workspace,
    set_active_workspace_id,
)

pytestmark = pytest.mark.local


def test_migration_015_and_workspace_product_isolation(tmp_path: Path) -> None:
    db_file = tmp_path / "phase01_isolation.db"
    migrate(db_file)

    # Migration 015 must seed default workspace id=1 and add workspace_id across core tables
    default_ws = get_workspace(db_file, DEFAULT_WORKSPACE_ID)
    assert default_ws is not None
    assert default_ws["slug"] == "default"
    assert default_ws["content_policy"] == "strict_footage"
    assert default_ws["approval_mode"] == "single"
    assert default_ws["default_aspect_ratio"] == "9:16"
    assert default_ws["archived"] is False

    for table in (
        "products",
        "footage",
        "assets",
        "videos",
        "accounts",
        "watch_items",
        "trend_items",
        "suggestions",
        "studio_sessions",
        "jobs",
    ):
        cols = {str(r["name"]) for r in query_all(db_file, f"PRAGMA table_info({table})")}
        assert "workspace_id" in cols, f"missing workspace_id on {table}"

    job_cols = {str(r["name"]) for r in query_all(db_file, "PRAGMA table_info(jobs)")}
    assert {"lane", "progress", "step"}.issubset(job_cols)

    idx_row = query_one(
        db_file,
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_jobs_lane_queue'",
    )
    assert idx_row is not None

    # Create a second workspace with Vietnamese name + custom policies
    ws2_id = create_workspace(
        db_file,
        name="Kênh Phim Đặc Biệt",
        niche="movie-recap",
        content_policy="hybrid_remix",
        approval_mode="bulk",
        default_aspect_ratio="16:9",
        style_preset="cinematic_wide",
    )
    ws2 = require_workspace(db_file, ws2_id)
    assert ws2["slug"] == "kenh-phim-dac-biet"
    assert ws2["content_policy"] == "hybrid_remix"
    assert ws2["approval_mode"] == "bulk"
    assert ws2["default_aspect_ratio"] == "16:9"

    with pytest.raises(ValueError, match="content_policy"):
        create_workspace(db_file, name="Bad Policy", content_policy="pirated")

    # Product isolation across workspaces
    p_default = create_product(
        db_file, name="Nhẫn Bạc Default", material="Bạc S925", workspace_id=DEFAULT_WORKSPACE_ID
    )
    p_ws2 = create_product(
        db_file, name="Loa Studio WS2", material="Hợp kim", workspace_id=ws2_id
    )

    default_items = list_products(db_file, workspace_id=DEFAULT_WORKSPACE_ID)
    ws2_items = list_products(db_file, workspace_id=ws2_id)
    all_items = list_products(db_file)

    assert [p["id"] for p in default_items] == [p_default]
    assert [p["id"] for p in ws2_items] == [p_ws2]
    assert ws2_items[0]["workspace_id"] == ws2_id
    assert sorted(p["id"] for p in all_items) == [p_default, p_ws2]

    # Missing workspace raises LookupError
    with pytest.raises(LookupError):
        create_product(db_file, name="Ghost", workspace_id=9999)

    # Activating and then archiving ws2 resets active workspace to default id=1
    set_active_workspace_id(db_file, ws2_id)
    assert get_active_workspace_id(db_file) == ws2_id

    archived_ws2 = archive_workspace(db_file, ws2_id)
    assert archived_ws2["archived"] is True
    assert get_active_workspace_id(db_file) == DEFAULT_WORKSPACE_ID
    assert [w["id"] for w in list_workspaces(db_file)] == [DEFAULT_WORKSPACE_ID]

    with pytest.raises(ValueError, match="archived"):
        create_product(db_file, name="Blocked", workspace_id=ws2_id)


def test_dual_lane_job_worker_parallel_io_and_serialized_compute(tmp_path: Path) -> None:
    db_file = tmp_path / "phase01_worker.db"
    migrate(db_file)

    assert classify_job_lane("studio") == "compute"
    assert classify_job_lane("render") == "compute"
    assert classify_job_lane("localize_render") == "compute"
    assert classify_job_lane("trends_scan") == "io"
    assert classify_job_lane("publish") == "io"

    reg = JobRegistry()
    lock = threading.Lock()
    io_active = 0
    io_max = 0
    compute_active = 0
    compute_max = 0
    both_lanes_overlapped = False

    io_barrier = threading.Barrier(3, timeout=4.0)
    compute_started = threading.Event()

    def io_handler(ref_id: int | None) -> str:
        nonlocal io_active, io_max, both_lanes_overlapped
        with lock:
            io_active += 1
            if io_active > io_max:
                io_max = io_active
            if compute_active > 0:
                both_lanes_overlapped = True
        try:
            # All 3 IO jobs MUST run simultaneously to pass this barrier
            io_barrier.wait()
            compute_started.wait(timeout=4.0)
            with lock:
                if compute_active > 0:
                    both_lanes_overlapped = True
            return f"io-{ref_id}"
        finally:
            with lock:
                io_active -= 1

    def compute_handler(ref_id: int | None) -> str:
        nonlocal compute_active, compute_max, both_lanes_overlapped
        with lock:
            compute_active += 1
            if compute_active > compute_max:
                compute_max = compute_active
            if io_active > 0:
                both_lanes_overlapped = True
        compute_started.set()
        try:
            time.sleep(0.12)
            with lock:
                if io_active > 0:
                    both_lanes_overlapped = True
            return f"compute-{ref_id}"
        finally:
            with lock:
                compute_active -= 1

    reg.register("test_io_parallel", io_handler, lane="io")
    reg.register("test_compute_serial", compute_handler, lane="compute")

    io_ids = [
        enqueue_job(db_file, "test_io_parallel", ref_id=i, registry=reg)
        for i in (1, 2, 3)
    ]
    compute_ids = [
        enqueue_job(db_file, "test_compute_serial", ref_id=i, registry=reg)
        for i in (10, 11)
    ]

    async def _run() -> None:
        worker = JobWorker(
            db_file,
            registry=reg,
            poll_interval_s=0.03,
            io_concurrency=3,
            compute_concurrency=1,
        )
        worker.start()
        try:
            deadline = time.monotonic() + 8.0
            all_ids = io_ids + compute_ids
            while time.monotonic() < deadline:
                jobs = [get_job(db_file, jid) for jid in all_ids]
                if all(j is not None and j["status"] == "done" for j in jobs):
                    break
                await asyncio.sleep(0.03)
            else:
                statuses = {jid: (get_job(db_file, jid) or {}).get("status") for jid in all_ids}
                pytest.fail(f"Dual-lane jobs did not finish within timeout: {statuses}")
        finally:
            await worker.stop()

    asyncio.run(_run())

    assert io_max == 3, f"Expected 3 concurrent IO jobs, got {io_max}"
    assert compute_max == 1, f"Expected serialized compute concurrency=1, got {compute_max}"
    assert both_lanes_overlapped, "Expected IO and compute lanes to execute concurrently"

    for jid in io_ids + compute_ids:
        row = get_job(db_file, jid)
        assert row is not None
        assert row["status"] == "done"
        assert row["progress"] == pytest.approx(1.0)


def test_dual_lane_queue_pause_and_resume(tmp_path: Path) -> None:
    db_file = tmp_path / "phase01_pause.db"
    migrate(db_file)

    reg = JobRegistry()
    reg.register("quick_io", lambda ref: f"done-{ref}", lane="io")

    async def _run() -> None:
        worker = JobWorker(
            db_file,
            registry=reg,
            poll_interval_s=0.03,
            io_concurrency=2,
            compute_concurrency=1,
        )
        worker.pause()
        assert is_queue_paused(db_file) is True
        assert worker.is_paused is True

        jid = enqueue_job(db_file, "quick_io", ref_id=42, registry=reg)
        worker.start()
        try:
            await asyncio.sleep(0.22)
            paused_job = get_job(db_file, jid)
            assert paused_job is not None
            assert paused_job["status"] == "queued"

            worker.resume()
            assert is_queue_paused(db_file) is False

            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                row = get_job(db_file, jid)
                if row is not None and row["status"] == "done":
                    break
                await asyncio.sleep(0.03)
            else:
                pytest.fail("Resumed job did not complete in time")
        finally:
            await worker.stop()

        done_job = get_job(db_file, jid)
        assert done_job is not None
        assert done_job["status"] == "done"
        assert done_job["log_tail"] == "done-42"

    asyncio.run(_run())


def test_v1_api_workspaces_jobs_logs_sse_and_cors_csrf(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    with TestClient(app) as client:
        # 1. Health endpoint
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        health_data = health.json()
        assert health_data["status"] == "ok"
        assert health_data["api_version"] == "v1"
        assert health_data["active_workspace_id"] == 1

        # 2. CORS preflight for local Next.js dev server
        preflight = client.options(
            "/api/v1/workspaces",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers.get("access-control-allow-origin") == "http://localhost:3000"

        # 3. Allowed cross-origin API mutation from localhost:3000
        create_resp = client.post(
            "/api/v1/workspaces",
            headers={"Origin": "http://localhost:3000"},
            json={
                "name": "Studio Trang Sức",
                "niche": "silver-jewelry",
                "content_policy": "strict_footage",
                "approval_mode": "bulk",
                "default_aspect_ratio": "9:16",
            },
        )
        assert create_resp.status_code == 201
        assert create_resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
        ws_data = create_resp.json()["workspace"]
        ws_id = int(ws_data["id"])
        assert ws_data["slug"] == "studio-trang-suc"
        assert ws_data["approval_mode"] == "bulk"

        # 4. CSRF blocks untrusted origin & browser cross-site & non-/api/v1 routes
        evil_resp = client.post(
            "/api/v1/workspaces",
            headers={"Origin": "https://evil.example"},
            json={"name": "Evil"},
        )
        assert evil_resp.status_code == 403

        cross_site_resp = client.post(
            "/api/v1/workspaces",
            headers={
                "Origin": "http://localhost:3000",
                "Sec-Fetch-Site": "cross-site",
            },
            json={"name": "Spoofed Cross-Site"},
        )
        assert cross_site_resp.status_code == 403

        legacy_form_csrf = client.post(
            "/products",
            headers={"Origin": "http://localhost:3000"},
            data={"name": "Blocked Form"},
        )
        assert legacy_form_csrf.status_code == 403

        # 5. Update + activate + archive workspace via /api/v1
        patch_resp = client.patch(
            f"/api/v1/workspaces/{ws_id}",
            json={"approval_mode": "autopilot", "style_preset": "bold_hook"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["workspace"]["approval_mode"] == "autopilot"
        assert patch_resp.json()["workspace"]["style_preset"] == "bold_hook"

        act_resp = client.post(f"/api/v1/workspaces/{ws_id}/activate")
        assert act_resp.status_code == 200
        assert act_resp.json()["active_workspace_id"] == ws_id
        assert client.get("/api/v1/health").json()["active_workspace_id"] == ws_id

        assert client.delete("/api/v1/workspaces/1").status_code == 400
        assert client.delete("/api/v1/workspaces/99999").status_code == 404

        del_resp = client.delete(f"/api/v1/workspaces/{ws_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["workspace"]["archived"] is True
        assert del_resp.json()["active_workspace_id"] == 1

        # 6. Dual-lane jobs & queue endpoints
        db_file = app.state.paths.db_file
        jid = enqueue_job(
            db_file,
            "studio_render",
            ref_id=7,
            lane="compute",
            workspace_id=1,
        )
        update_job_progress(db_file, jid, progress=0.45, step="rendering_scenes")

        jobs_resp = client.get("/api/v1/jobs", params={"lane": "compute", "workspace_id": 1})
        assert jobs_resp.status_code == 200
        jobs_payload = jobs_resp.json()
        assert len(jobs_payload["jobs"]) == 1
        assert jobs_payload["jobs"][0]["id"] == jid
        assert jobs_payload["jobs"][0]["progress"] == pytest.approx(0.45)
        assert jobs_payload["jobs"][0]["step"] == "rendering_scenes"

        assert client.get(f"/api/v1/jobs/{jid}").json()["job"]["lane"] == "compute"
        assert client.get("/api/v1/jobs/999999").status_code == 404

        q_status = client.get("/api/v1/queue/status").json()
        assert q_status["paused"] is False
        assert q_status["by_lane"]["compute"]["queued"] == 1

        pause_resp = client.post(
            "/api/v1/queue/pause",
            headers={"Origin": "http://localhost:3000"},
        )
        assert pause_resp.status_code == 200
        assert pause_resp.json()["paused"] is True

        resume_resp = client.post(
            "/api/v1/queue/resume",
            headers={"Origin": "http://localhost:3000"},
        )
        assert resume_resp.status_code == 200
        assert resume_resp.json()["paused"] is False

        # 7. Logs tail & SSE one-shot snapshot
        log_file = app.state.paths.log_file
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write("v2-phase01-marker-line\n")

        logs_resp = client.get("/api/v1/logs/tail", params={"lines": 20})
        assert logs_resp.status_code == 200
        assert "v2-phase01-marker-line" in logs_resp.json()["lines"]

        sse_resp = client.get("/api/v1/events", params={"once": "true"})
        assert sse_resp.status_code == 200
        assert sse_resp.headers["content-type"].startswith("text/event-stream")
        assert "event: queue_snapshot" in sse_resp.text
        data_lines = [
            line[len("data: ") :]
            for line in sse_resp.text.splitlines()
            if line.startswith("data: ")
        ]
        assert len(data_lines) == 1
        snap = json.loads(data_lines[0])
        assert snap["active_workspace_id"] == 1
        assert snap["queue"] == get_queue_summary(db_file)
        assert any(j["id"] == jid for j in snap["recent_jobs"])


def test_non_localhost_v1_health_public_and_other_routes_protected(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, bind_host="0.0.0.0", start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/workspaces").status_code == 401
