"""Wave 1 regression & reproduction tests for verified security, crash-loop, client, and restore bugs."""
from __future__ import annotations

import base64
import json
import socket
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from videocreator.__main__ import start_nextjs_standalone, stop_nextjs_standalone, wait_for_health
from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_one
from videocreator.job_store import (
    claim_next_queued_job,
    recover_interrupted_jobs,
)
from videocreator.jobs import enqueue_job
from videocreator.paths import REPO_ROOT, find_node_runtime, get_paths
from videocreator.secrets_store import SecretsStore
from videocreator.transfer import export_config_bundle, import_config_bundle

pytestmark = pytest.mark.local


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _raw_http(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with opener.open(req, timeout=15.0) as resp:
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return int(resp.status), hdrs, resp.read()
    except urllib.error.HTTPError as exc:
        hdrs = {k.lower(): v for k, v in exc.headers.items()}
        return int(exc.code), hdrs, exc.read()


def test_bug_1_1_and_1_2_nextjs_proxy_csrf_and_lan_basic_auth_headers(tmp_path: Path) -> None:
    """1.1: Cross-origin mutations through Next.js proxy must return 403 (not strip Origin/Sec-Fetch-Site).
    1.2: Non-localhost Basic Auth `WWW-Authenticate` header must pass through Next.js proxy on 401.
    """
    paths = get_paths(tmp_path / "data")
    api_port = _free_port()
    ui_port = _free_port()
    while ui_port == api_port:
        ui_port = _free_port()

    api_base = f"http://127.0.0.1:{api_port}"
    ui_base = f"http://127.0.0.1:{ui_port}"

    # Configure non-localhost bind_host="0.0.0.0" + UI_PASSWORD so we test BOTH CSRF and Basic Auth headers!
    app = create_app(paths.data_dir, start_worker=False, bind_host="0.0.0.0")
    secrets: SecretsStore = app.state.secrets
    secrets.set("UI_PASSWORD", "LanSecret2026")
    auth_hdr = "Basic " + base64.b64encode(b"admin:LanSecret2026").decode("ascii")

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    ui_proc: Any = None
    try:
        assert wait_for_health(f"{api_base}/health", timeout_s=20.0, server_thread=thread)
        ui_proc = start_nextjs_standalone(
            ui_port,
            api_base,
            boot_log_path=paths.logs_dir / "next_csrf_e2e.log",
            host="127.0.0.1",
            timeout_s=25.0,
        )
        assert ui_proc is not None

        # 1.2: Unauthenticated request to `/api/v1/workspaces` through Next.js proxy returns 401 WITH www-authenticate
        st_401, hdrs_401, _ = _raw_http(f"{ui_base}/api/v1/workspaces")
        assert st_401 == 401
        assert "basic" in hdrs_401.get("www-authenticate", "").lower(), hdrs_401

        # Authenticated GET succeeds
        st_200, _, _ = _raw_http(
            f"{ui_base}/api/v1/workspaces",
            headers={"Authorization": auth_hdr},
        )
        assert st_200 == 200

        # 1.1a: Cross-origin POST (`Origin: https://evil.example`) through Next.js proxy MUST be blocked (403)
        st_evil_origin, _, _ = _raw_http(
            f"{ui_base}/api/v1/queue/pause",
            method="POST",
            headers={
                "Authorization": auth_hdr,
                "Origin": "https://evil.example",
            },
        )
        assert st_evil_origin == 403

        # 1.1b: `Sec-Fetch-Site: cross-site` without Origin header MUST be blocked (403)
        st_cross_site, _, _ = _raw_http(
            f"{ui_base}/api/v1/queue/pause",
            method="POST",
            headers={
                "Authorization": auth_hdr,
                "Sec-Fetch-Site": "cross-site",
            },
        )
        assert st_cross_site == 403

        # 1.1c: Same-origin POST from the Next.js UI origin (`Origin: ui_base`) MUST succeed (200)
        st_legit, _, _ = _raw_http(
            f"{ui_base}/api/v1/queue/pause",
            method="POST",
            headers={
                "Authorization": auth_hdr,
                "Origin": ui_base,
                "Sec-Fetch-Site": "same-origin",
            },
        )
        assert st_legit == 200

        # 1.1d: Proxied `/api/editor/heartbeat` mutation from `ui_base` also succeeds while evil origin fails
        st_ed_evil, _, _ = _raw_http(
            f"{ui_base}/api/editor/heartbeat",
            method="POST",
            body=b'{"job":"j1","closing":false}',
            headers={
                "Authorization": auth_hdr,
                "Content-Type": "application/json",
                "Origin": "https://evil.example",
            },
        )
        assert st_ed_evil == 403

        st_ed_ok, _, _ = _raw_http(
            f"{ui_base}/api/editor/heartbeat",
            method="POST",
            body=b'{"job":"j1","closing":false}',
            headers={
                "Authorization": auth_hdr,
                "Content-Type": "application/json",
                "Origin": ui_base,
                "Sec-Fetch-Site": "same-origin",
            },
        )
        assert st_ed_ok == 200
    finally:
        stop_nextjs_standalone(ui_proc)
        server.should_exit = True
        thread.join(timeout=5.0)


def test_bug_1_3_job_crash_loop_capped_by_max_attempts_and_manual_retry(tmp_path: Path) -> None:
    """1.3: Jobs crashing the process repeatedly must transition to `failed` after MAX_JOB_ATTEMPTS (3),
    and manual `POST /api/v1/jobs/{id}/retry` resets `attempts = 0`.
    """
    app = create_app(tmp_path / "data", start_worker=False)
    db_file = app.state.paths.db_file

    jid = enqueue_job(db_file, "render", ref_id=999, lane="compute")

    # Simulate 2 process crashes mid-execution -> still requeued on recovery
    for expected_attempt in (1, 2):
        claimed = claim_next_queued_job(db_file, lane="compute")
        assert claimed is not None and int(claimed["id"]) == jid
        assert int(claimed["attempts"]) == expected_attempt
        recover_interrupted_jobs(db_file)
        row = query_one(db_file, "SELECT status, attempts, error FROM jobs WHERE id = ?", (jid,))
        assert row is not None
        assert row["status"] == "queued"
        assert int(row["attempts"]) == expected_attempt

    # 3rd crash -> reaches MAX_JOB_ATTEMPTS (3) -> marked `failed` instead of looping forever!
    claimed3 = claim_next_queued_job(db_file, lane="compute")
    assert claimed3 is not None and int(claimed3["attempts"]) == 3
    recover_interrupted_jobs(db_file)
    crashed_row = query_one(db_file, "SELECT status, attempts, error FROM jobs WHERE id = ?", (jid,))
    assert crashed_row is not None
    assert crashed_row["status"] == "failed"
    assert "gián đoạn" in str(crashed_row["error"] or "").lower()

    # Manual retry via API resets attempts = 0 and status = 'queued'
    with TestClient(app) as client:
        res = client.post(f"/api/v1/jobs/{jid}/retry")
        assert res.status_code == 200
        retried = res.json()["job"]
        assert retried["status"] == "queued"
        assert int(retried["attempts"]) == 0
        assert retried["error"] is None


def test_bug_1_4_apifetch_preserves_plain_text_error_and_handles_204() -> None:
    """1.4 & 1.6: `apiFetch` / `parseApiResponse` preserves plain-text error bodies (no body double-read),
    returns `undefined` on 204/empty body, throws typed `ApiError(status, message)`, and forwards `AbortSignal`.
    """
    node_bin = find_node_runtime()
    assert node_bin is not None
    api_ts = (REPO_ROOT / "web-next" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "ApiError" in api_ts
    assert "parseApiResponse" in api_ts

    script = """
    import assert from 'node:assert/strict';
    import fs from 'node:fs';

    // Strip React client context part and dynamically evaluate ApiError + parseApiResponse + apiFetch via TS strip
    const fullSrc = fs.readFileSync('web-next/src/lib/api.ts', 'utf8');
    const cutIdx = fullSrc.indexOf('interface WorkspaceContextValue');
    const pureClientTs = fullSrc.slice(0, cutIdx).replace('"use client";', '');
    const tmpMts = 'web-next/.next_apifetch_probe.mts';
    fs.writeFileSync(tmpMts, pureClientTs, 'utf8');
    try {
      const mod = await import('./web-next/.next_apifetch_probe.mts');
      // 1) Plain-text 502 error body must NOT throw TypeError: Body is unusable
      await assert.rejects(
        () => mod.parseApiResponse(new Response('Upstream Gateway Timeout Plaintext', { status: 502 })),
        (err) => err instanceof mod.ApiError && err.status === 502 && err.message === 'Upstream Gateway Timeout Plaintext'
      );
      // 2) JSON {detail} 422 error body extracts detail string & status
      await assert.rejects(
        () => mod.parseApiResponse(new Response(JSON.stringify({ detail: 'Thiếu trường bắt buộc' }), { status: 422 })),
        (err) => err instanceof mod.ApiError && err.status === 422 && err.message === 'Thiếu trường bắt buộc'
      );
      // 3) 204 No Content returns undefined without JSON parse error
      const res204 = await mod.parseApiResponse(new Response(null, { status: 204 }));
      assert.equal(res204, undefined);
      // 4) AbortSignal is forwarded cleanly to global fetch (1.6 prerequisite)
      const ac = new AbortController();
      ac.abort();
      await assert.rejects(
        () => mod.apiFetch('http://127.0.0.1:9/api/v1/dashboard', { signal: ac.signal }),
        (err) => err && err.name === 'AbortError'
      );
    } finally {
      fs.rmSync(tmpMts, { force: true });
    }
    """
    proc = subprocess.run(
        [node_bin, "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


def test_bug_1_5_vcx_restore_rejects_newer_schema_and_recovers_running_jobs(tmp_path: Path) -> None:
    """1.5: Restoring `.vcx` must reject newer `PRAGMA user_version` without corrupting target DB,
    and must recover any job that was `running` when the backup snapshot was taken.
    """
    src_paths = get_paths(tmp_path / "src_machine")
    dst_paths = get_paths(tmp_path / "dst_machine")
    migrate(src_paths.db_file)
    migrate(dst_paths.db_file)

    # 1. Put a `running` job into src_machine before exporting `.vcx`
    jid = enqueue_job(src_paths.db_file, "novel_render", ref_id=1, lane="compute")
    claim_next_queued_job(src_paths.db_file, lane="compute")
    row_before = query_one(src_paths.db_file, "SELECT status FROM jobs WHERE id = ?", (jid,))
    assert row_before is not None and row_before["status"] == "running"

    good_vcx = tmp_path / "with_running_job.vcx"
    export_config_bundle(src_paths, "Pass1234", good_vcx)

    import_config_bundle(dst_paths, good_vcx, "Pass1234", as_server=True)
    row_after = query_one(dst_paths.db_file, "SELECT status FROM jobs WHERE id = ?", (jid,))
    assert row_after is not None
    assert row_after["status"] == "queued", "Stuck `running` job from backup must be recovered to `queued`"

    # 2. Export a bundle whose SQLite `user_version` is from a future app release (e.g. 999)
    future_paths = get_paths(tmp_path / "future_machine")
    migrate(future_paths.db_file)
    conn = sqlite3.connect(str(future_paths.db_file))
    try:
        conn.execute("PRAGMA user_version = 999;")
        conn.commit()
    finally:
        conn.close()
    future_vcx = tmp_path / "future_schema.vcx"
    export_config_bundle(future_paths, "Pass1234", future_vcx)

    cfg_before = load_settings(dst_paths.config_file)
    cfg_before.budget.daily_usd = 12.5
    save_settings(dst_paths.config_file, cfg_before)

    with pytest.raises(ValueError, match="phiên bản mới hơn|user_version|newer"):
        import_config_bundle(dst_paths, future_vcx, "Pass1234", as_server=True)

    # Target config & DB must remain untouched when future schema bundle is rejected!
    assert load_settings(dst_paths.config_file).budget.daily_usd == 12.5
