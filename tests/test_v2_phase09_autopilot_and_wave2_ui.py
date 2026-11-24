"""Tests for Phase 09: Channel Autopilot Engine & Wave 2 Next.js Studio Views."""
from __future__ import annotations

import json
import socket
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from videocreator.__main__ import (
    start_nextjs_standalone,
    stop_nextjs_standalone,
    wait_for_health,
)
from videocreator.app import create_app
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import REPO_ROOT, get_paths
from videocreator.posting.accounts import upsert_account

pytestmark = pytest.mark.local


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_autopilot_rss_dedup_daily_cap_and_score_gate(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        # strict_footage blocks localize_trends and shotless rss_feed rules
        b1 = client.post(
            "/api/v1/autopilot/rules",
            json={"workspace_id": 1, "name": "Bad Loc", "source_mode": "localize_trends"},
        )
        assert b1.status_code == 403

        rss_file = tmp_path / "feed.xml"
        rss_file.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Bac S925 News</title>
    <item>
      <guid>item-001</guid>
      <title>Xu huong nhan bac toi gian 2026</title>
      <description>&lt;p&gt;Thiet ke manh de phoi do hang ngay.&lt;/p&gt;</description>
      <link>https://example.com/news/1</link>
    </item>
    <item>
      <guid>item-002</guid>
      <title>Cach bao quan day chuyen bac S925</title>
      <description>Lau bang khan mem sau khi su dung.</description>
      <link>https://example.com/news/2</link>
    </item>
    <item>
      <guid>item-003</guid>
      <title>Bi quyet tang qua bac y nghia</title>
      <description>Goi hop sang trong kem the bao hanh.</description>
      <link>https://example.com/news/3</link>
    </item>
  </channel>
</rss>
""",
            encoding="utf-8",
        )

        b2 = client.post(
            "/api/v1/autopilot/rules",
            json={
                "workspace_id": 1,
                "name": "Shotless RSS",
                "source_mode": "rss_feed",
                "feed_url": str(rss_file),
            },
        )
        assert b2.status_code == 403

        # Create full_ai workspace + autopilot YouTube channel
        ws_res = client.post(
            "/api/v1/workspaces",
            json={
                "name": "News Autopilot YT",
                "content_policy": "full_ai",
                "approval_mode": "autopilot",
            },
        )
        assert ws_res.status_code == 201
        ws_id = int(ws_res.json()["workspace"]["id"])

        acct_id = upsert_account(
            paths,
            platform="youtube",
            external_id="UC_AUTOPILOT_01",
            name="News Shorts YT",
            access_token="yt_tok_autopilot",
            workspace_id=ws_id,
            approval_mode="autopilot",
            autopilot_min_score=8.0,
        )
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE accounts SET slots_json = ? WHERE id = ?",
                (json.dumps(["09:00", "20:00"]), acct_id),
            )

        # Rule 1: daily_cap = 2, min_quality_score = 8.0 -> auto-approves & schedules
        r_res = client.post(
            "/api/v1/autopilot/rules",
            json={
                "workspace_id": ws_id,
                "name": "Daily RSS Shorts",
                "source_mode": "rss_feed",
                "feed_url": str(rss_file),
                "target_account_ids": [acct_id],
                "daily_cap": 2,
                "min_quality_score": 8.0,
            },
        )
        assert r_res.status_code == 201, r_res.text
        rule_id = int(r_res.json()["rule"]["id"])

        t1 = client.post(
            f"/api/v1/autopilot/rules/{rule_id}/trigger",
            json={"sync": True, "force": True, "score_override": 8.7},
        )
        assert t1.status_code == 200
        res1 = t1.json()["results"][0]
        assert res1["status"] == "scheduled"
        assert res1["scheduled"] is True
        vid1 = int(res1["video_id"])
        assert query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (vid1,))["status"] == "scheduled"

        t2 = client.post(
            f"/api/v1/autopilot/rules/{rule_id}/trigger",
            json={"sync": True, "force": True, "score_override": 8.9},
        )
        assert t2.status_code == 200
        res2 = t2.json()["results"][0]
        assert res2["status"] == "scheduled"
        vid2 = int(res2["video_id"])
        assert vid2 != vid1

        posts = query_all(
            paths.db_file,
            "SELECT * FROM posts WHERE account_id = ? ORDER BY id ASC",
            (acct_id,),
        )
        assert len(posts) == 2
        assert all(p["status"] == "scheduled" for p in posts)

        # Trigger #3 hits daily_cap = 2
        t3 = client.post(
            f"/api/v1/autopilot/rules/{rule_id}/trigger",
            json={"sync": True, "force": True},
        )
        assert t3.status_code == 200
        assert t3.json()["results"][0]["status"] == "daily_cap_reached"

        # Rule 2 with strict min_quality_score=9.8 holds low-scoring video (8.6) in pending_approval
        r2_res = client.post(
            "/api/v1/autopilot/rules",
            json={
                "workspace_id": ws_id,
                "name": "Strict Score Gate",
                "source_mode": "rss_feed",
                "feed_url": str(rss_file),
                "target_account_ids": [acct_id],
                "daily_cap": 3,
                "min_quality_score": 9.8,
            },
        )
        assert r2_res.status_code == 201
        r2_id = int(r2_res.json()["rule"]["id"])
        tg = client.post(
            f"/api/v1/autopilot/rules/{r2_id}/trigger",
            json={"sync": True, "force": True, "score_override": 8.6},
        )
        assert tg.status_code == 200
        res_gate = tg.json()["results"][0]
        assert res_gate["status"] == "pending_review"
        assert res_gate["scheduled"] is False
        gated_vid = int(res_gate["video_id"])
        assert query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (gated_vid,))["status"] == "pending_approval"
        assert len(query_all(paths.db_file, "SELECT * FROM posts WHERE video_id = ?", (gated_vid,))) == 0

        # Check runs API
        runs = client.get(f"/api/v1/autopilot/runs?workspace_id={ws_id}").json()["runs"]
        assert len(runs) == 3


def test_wave2_nextjs_standalone_views(tmp_path: Path) -> None:
    standalone = REPO_ROOT / "web-next" / ".next" / "standalone" / "server.js"
    assert standalone.is_file(), f"Missing Next.js standalone build at {standalone}"

    paths = get_paths(tmp_path / "data")
    api_port = _free_port()
    ui_port = _free_port()
    while ui_port == api_port:
        ui_port = _free_port()

    api_base = f"http://127.0.0.1:{api_port}"
    ui_base = f"http://127.0.0.1:{ui_port}"
    app = create_app(paths.data_dir, bind_host="127.0.0.1")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    ui_proc: Any = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        assert wait_for_health(f"{api_base}/health", timeout_s=20.0, server_thread=thread)
        ui_proc = start_nextjs_standalone(
            ui_port,
            api_base,
            boot_log_path=paths.logs_dir / "next_w2.log",
            host="127.0.0.1",
            timeout_s=25.0,
        )
        assert ui_proc is not None

        for path in ("/localize", "/batch", "/autopilot", "/trends", "/settings"):
            with opener.open(f"{ui_base}{path}", timeout=15.0) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8", errors="replace")
                assert len(body) > 200

        for api_path in (
            "/api/v1/localize/projects",
            "/api/v1/batches",
            "/api/v1/autopilot/rules",
            "/api/v1/models",
            "/api/v1/key-pool",
        ):
            with opener.open(f"{ui_base}{api_path}", timeout=15.0) as resp:
                assert resp.status == 200
    finally:
        stop_nextjs_standalone(ui_proc)
        server.should_exit = True
        thread.join(timeout=5.0)
