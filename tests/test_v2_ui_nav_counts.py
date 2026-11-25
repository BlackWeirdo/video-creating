"""Tests for SSE `nav_counts` badge telemetry and Wave 1 UI token hygiene."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.api.v1.routes_system import clear_nav_counts_cache, get_nav_counts
from videocreator.app import create_app
from videocreator.db import get_write_conn
from videocreator.workspaces import create_workspace

pytestmark = pytest.mark.local

REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse_sse_snapshot(raw_text: str) -> dict:
    data_lines = [
        line[len("data: ") :]
        for line in raw_text.splitlines()
        if line.startswith("data: ")
    ]
    assert len(data_lines) == 1
    return json.loads(data_lines[0])


def test_sse_nav_counts_pending_approvals_suggestions_and_failed_routes(tmp_path: Path) -> None:
    clear_nav_counts_cache()
    app = create_app(data_dir=tmp_path, start_worker=False)
    db_file: Path = app.state.paths.db_file

    with TestClient(app) as client:
        snap0 = _parse_sse_snapshot(client.get("/api/v1/events", params={"once": "true"}).text)
        assert snap0["nav_counts"] == {
            "approvals_pending": 0,
            "suggestions_new": 0,
            "failed_routes": [],
        }

        ws2_id = int(create_workspace(db_file, name="Brand Two", niche="fashion"))

        with get_write_conn(db_file) as conn:
            # 2 pending approvals in ws 1, 1 approved, 1 in ws 2
            conn.execute(
                "INSERT INTO videos (workspace_id, status, aspect_ratio, style_preset) VALUES (1, 'pending_approval', '9:16', 'clean')"
            )
            conn.execute(
                "INSERT INTO videos (workspace_id, status, aspect_ratio, style_preset) VALUES (1, 'pending_approval', '9:16', 'clean')"
            )
            conn.execute(
                "INSERT INTO videos (workspace_id, status, aspect_ratio, style_preset) VALUES (1, 'approved', '9:16', 'clean')"
            )
            conn.execute(
                "INSERT INTO videos (workspace_id, status, aspect_ratio, style_preset) VALUES (?, 'pending_approval', '9:16', 'clean')",
                (ws2_id,),
            )

            # 2 active suggestions in ws 1 ('new' and 'sent'), 1 dismissed
            conn.execute(
                "INSERT INTO suggestions (workspace_id, text, status) VALUES (1, 'Hook A', 'new')"
            )
            conn.execute(
                "INSERT INTO suggestions (workspace_id, text, status) VALUES (1, 'Hook B', 'sent')"
            )
            conn.execute(
                "INSERT INTO suggestions (workspace_id, text, status) VALUES (1, 'Hook C', 'dismissed')"
            )

            # Recent failed jobs in ws 1 -> /localize and /news, plus stale (>24h) failed job -> /podcast
            conn.execute(
                """
                INSERT INTO jobs (workspace_id, kind, status, lane, finished_at)
                VALUES (1, 'localize_extract', 'failed', 'compute', strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hours'))
                """
            )
            conn.execute(
                """
                INSERT INTO jobs (workspace_id, kind, status, lane, finished_at)
                VALUES (1, 'news_render', 'failed', 'compute', strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-2 hours'))
                """
            )
            conn.execute(
                """
                INSERT INTO jobs (workspace_id, kind, status, lane, finished_at)
                VALUES (1, 'podcast_render', 'failed', 'compute', strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-30 hours'))
                """
            )

        snap1 = _parse_sse_snapshot(client.get("/api/v1/events", params={"once": "true"}).text)
        assert snap1["nav_counts"]["approvals_pending"] == 2
        assert snap1["nav_counts"]["suggestions_new"] == 2
        assert snap1["nav_counts"]["failed_routes"] == ["/localize", "/news"]

        # Workspace 2 isolation check
        snap_ws2 = _parse_sse_snapshot(
            client.get(
                "/api/v1/events",
                params={"once": "true", "workspace_id": str(ws2_id)},
            ).text
        )
        assert snap_ws2["nav_counts"]["approvals_pending"] == 1
        assert snap_ws2["nav_counts"]["suggestions_new"] == 0
        assert snap_ws2["nav_counts"]["failed_routes"] == []

        # Verify TTL cache prevents redundant SQLite queries within TTL window
        clear_nav_counts_cache()
        first_cached = get_nav_counts(db_file, ws_id=1, use_cache=True, ttl_s=60.0)
        assert first_cached["approvals_pending"] == 2
        with get_write_conn(db_file) as conn:
            conn.execute(
                "INSERT INTO videos (workspace_id, status, aspect_ratio, style_preset) VALUES (1, 'pending_approval', '9:16', 'clean')"
            )
        still_cached = get_nav_counts(db_file, ws_id=1, use_cache=True, ttl_s=60.0)
        assert still_cached["approvals_pending"] == 2
        refreshed = get_nav_counts(db_file, ws_id=1, use_cache=False)
        assert refreshed["approvals_pending"] == 3


def test_wave1_ui_files_have_no_hardcoded_hex_classes() -> None:
    web_src = REPO_ROOT / "web-next" / "src"
    targets = [
        web_src / "components",
        web_src / "app" / "page.tsx",
        web_src / "app" / "localize",
        web_src / "app" / "approval",
        web_src / "app" / "settings",
    ]
    hex_class_re = re.compile(r"(?:bg|text|border)-\[#[0-9a-fA-F]{3,8}\]")
    offenders: list[str] = []
    for t in targets:
        files = [t] if t.is_file() else sorted(t.rglob("*.ts*"))
        for f in files:
            txt = f.read_text(encoding="utf-8")
            if hex_class_re.search(txt):
                offenders.append(f.relative_to(REPO_ROOT).as_posix())
    assert offenders == [], f"Found hardcoded hex Tailwind classes in Wave 1 UI files: {offenders}"
