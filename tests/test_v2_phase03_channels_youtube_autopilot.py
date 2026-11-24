"""Real SQLite + FFmpeg + OAuth/HTTP tests for V2 Phase 03 (YouTube, .zip Pack, 3-Tier Approvals)."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from videocreator.approvals import (
    approve,
    bulk_approve,
    try_autopilot_approve,
)
from videocreator.db import get_conn, migrate, query_all, query_one
from videocreator.paths import get_paths
from videocreator.pipeline.export import normalize_to_master
from videocreator.pipeline.preflight import check_all_platforms
from videocreator.posting.accounts import upsert_account
from videocreator.posting.metrics import collect_due_metrics
from videocreator.posting.oauth import build_authorize_url
from videocreator.posting.oauth_exchange import exchange_code_for_account
from videocreator.posting.oauth_refresh import refresh_token_if_needed
from videocreator.posting.publish import publish_due_posts
from videocreator.posting.publish_pack import build_publish_pack_zip
from videocreator.posting.youtube import YouTubePoster
from videocreator.secrets_store import SecretsStore
from videocreator.workspaces import create_workspace

pytestmark = pytest.mark.local

SAMPLE_CLIP_1 = Path(__file__).resolve().parent / "samples" / "clip1_6s.mp4"


def test_migration_017_preserves_existing_accounts_and_posts_with_fk(tmp_path: Path) -> None:
    from videocreator.db import DEFAULT_MIGRATIONS_DIR
    import shutil

    mig16_dir = tmp_path / "mig16"
    mig16_dir.mkdir()
    for f in sorted(DEFAULT_MIGRATIONS_DIR.glob("*.sql")):
        prefix = f.name.split("_", 1)[0]
        if prefix.isdigit() and int(prefix) >= 17:
            continue
        shutil.copy2(f, mig16_dir / f.name)

    db_file = tmp_path / "upgrade17.db"
    assert migrate(db_file, migrations_dir=mig16_dir) == 16

    with get_conn(db_file) as conn:
        conn.execute(
            "INSERT INTO accounts (id, platform, external_id, name, lang, secret_key, workspace_id) "
            "VALUES (10, 'tiktok', 'tt_old_1', 'Old TikTok', 'vi', 'KEY_OLD_1', 1)"
        )
        conn.execute("INSERT INTO videos (id, status, plan_json) VALUES (50, 'scheduled', '{}')")
        conn.execute(
            "INSERT INTO posts (id, video_id, account_id, status, scheduled_at) "
            "VALUES (100, 50, 10, 'scheduled', '2026-11-24T12:00:00Z')"
        )

    assert migrate(db_file) >= 17

    with get_conn(db_file) as conn:
        fk_check = conn.execute("PRAGMA foreign_key_check;").fetchall()
        assert fk_check == []
        fk_enabled = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert fk_enabled == 1

    acc = query_one(db_file, "SELECT * FROM accounts WHERE id = 10")
    assert acc is not None
    assert acc["platform"] == "tiktok"
    assert acc["approval_mode"] == "inherit"

    post = query_one(db_file, "SELECT * FROM posts WHERE id = 100")
    assert post is not None
    assert post["account_id"] == 10


def test_youtube_oauth_exchange_refresh_resumable_upload_and_metrics(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    sec = SecretsStore(paths.secrets_file)
    sec.set("GOOGLE_CLIENT_ID", "g_client_id_test")
    sec.set("GOOGLE_CLIENT_SECRET", "g_client_secret_test")

    ws2_id = create_workspace(
        paths.db_file, name="Kênh YouTube V2", content_policy="full_ai", approval_mode="autopilot"
    )
    t0 = datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc)

    auth_url, state = build_authorize_url(
        paths,
        "youtube",
        redirect_uri="http://127.0.0.1:8765/oauth/youtube/callback",
        workspace_id=ws2_id,
        now_dt=t0,
        secrets_store=sec,
    )
    assert "accounts.google.com/o/oauth2/v2/auth" in auth_url
    assert f"state={state}" in auth_url

    seen_calls: list[tuple[str, str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen_calls.append((request.method, str(request.url)))
        url = str(request.url)
        if "oauth2.googleapis.com/token" in url:
            body = request.content.decode("utf-8", errors="ignore")
            if "refresh_token" in body:
                return httpx.Response(
                    200,
                    json={"access_token": "yt_access_refreshed_2", "expires_in": 3600},
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "yt_access_initial_1",
                    "refresh_token": "yt_refresh_perm_1",
                    "expires_in": 3600,
                },
            )
        if "youtube/v3/channels" in url:
            return httpx.Response(
                200,
                json={"items": [{"id": "UC_V2_SILVER_99", "snippet": {"title": "Tiệm Bạc Shorts"}}]},
            )
        if "upload/youtube/v3/videos" in url and request.method == "POST":
            meta = json.loads(request.content.decode("utf-8"))
            assert "#Shorts" in meta["snippet"]["title"]
            return httpx.Response(
                200,
                headers={"Location": "https://www.googleapis.com/upload/youtube/v3/session_abc"},
                json={},
            )
        if "upload/youtube/v3/session_abc" in url and request.method == "PUT":
            assert len(request.content) > 5_000
            return httpx.Response(200, json={"id": "yt_vid_8899"})
        if "youtube/v3/videos" in url and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "yt_vid_8899",
                            "statistics": {"viewCount": "1420", "likeCount": "95", "commentCount": "12"},
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"error": "unhandled"})

    http_client = httpx.Client(transport=httpx.MockTransport(_handler))
    try:
        acc_id = exchange_code_for_account(
            paths,
            "youtube",
            code="google_auth_code_xyz",
            state=state,
            now_dt=t0,
            secrets_store=sec,
            http_client=http_client,
        )
        acc = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = ?", (acc_id,))
        assert acc is not None
        assert acc["platform"] == "youtube"
        assert acc["external_id"] == "UC_V2_SILVER_99"
        assert acc["workspace_id"] == ws2_id
        assert sec.get(str(acc["secret_key"])) == "yt_access_initial_1"
        assert sec.get(f"{acc['secret_key']}_REFRESH") == "yt_refresh_perm_1"

        # Refresh near expiry (< 10 min)
        refreshed = refresh_token_if_needed(
            paths,
            acc,
            now_dt=t0 + timedelta(minutes=55),
            secrets_store=sec,
            http_client=http_client,
        )
        assert refreshed is True
        assert sec.get(str(acc["secret_key"])) == "yt_access_refreshed_2"

        # Real 6s portrait master MP4 uploaded through YouTubePoster + metrics collection
        master_rel = "output/video_yt_1.mp4"
        master_abs = paths.media_dir / master_rel
        normalize_to_master(SAMPLE_CLIP_1, master_abs, preset="ultrafast")

        plan_json = json.dumps({"title": "Nhẫn Bạc Chế Tác Tay"}, ensure_ascii=False)
        caps_json = json.dumps(
            {"youtube": {"text": "Xem chi tiết mẫu mới", "hashtags": ["#bacthucong"]}},
            ensure_ascii=False,
        )
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                INSERT INTO videos (id, workspace_id, status, output_path, plan_json, captions_json)
                VALUES (1, ?, 'scheduled', ?, ?, ?)
                """,
                (ws2_id, master_rel, plan_json, caps_json),
            )
            conn.execute(
                """
                INSERT INTO posts (id, video_id, account_id, status, scheduled_at)
                VALUES (1, 1, ?, 'scheduled', ?)
                """,
                (acc_id, (t0 - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )

        yt_poster = YouTubePoster(paths, sec, http_client=http_client)
        processed = publish_due_posts(
            paths, poster_overrides={"youtube": yt_poster}, now_dt=t0
        )
        assert processed == 1

        post_done = query_one(paths.db_file, "SELECT * FROM posts WHERE id = 1")
        assert post_done is not None
        assert post_done["status"] == "posted"
        assert post_done["external_post_id"] == "yt_vid_8899"
        assert post_done["permalink"] == "https://www.youtube.com/shorts/yt_vid_8899"

        # Collect 24h metrics
        saved_cp = collect_due_metrics(
            paths,
            now_dt=t0 + timedelta(hours=25),
            reader_overrides={"youtube": yt_poster},
        )
        assert saved_cp == 1
        metric_row = query_one(paths.db_file, "SELECT * FROM post_metrics WHERE post_id = 1")
        assert metric_row is not None
        assert metric_row["views"] == 1420
        assert metric_row["likes"] == 95
        assert metric_row["comments"] == 12
    finally:
        http_client.close()


def test_five_platform_zip_pack_workspace_isolation_bulk_and_autopilot(tmp_path: Path) -> None:
    from videocreator.config import load_settings

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    cfg = load_settings(paths.config_file)
    sec = SecretsStore(paths.secrets_file)

    ws_strict = 1  # default workspace: strict_footage, single
    ws_auto = create_workspace(
        paths.db_file,
        name="Auto Satellite Channel",
        content_policy="full_ai",
        approval_mode="autopilot",
    )

    acc_strict = upsert_account(
        paths,
        platform="tiktok",
        external_id="acc_strict_1",
        name="Brand TikTok",
        access_token="tok1",
        workspace_id=ws_strict,
        secrets_store=sec,
    )
    acc_auto_yt = upsert_account(
        paths,
        platform="youtube",
        external_id="acc_auto_yt",
        name="Satellite Shorts",
        access_token="tok2",
        workspace_id=ws_auto,
        approval_mode="autopilot",
        autopilot_min_score=7.5,
        secrets_store=sec,
    )

    master_rel = "output/video_pack_1.mp4"
    master_abs = paths.media_dir / master_rel
    normalize_to_master(SAMPLE_CLIP_1, master_abs, preset="ultrafast")
    preflight_ok = json.dumps(check_all_platforms(master_abs, cfg))
    qc_ok = json.dumps({"passed": True, "issues": [], "integrated_lufs": -14.1})
    qc_bad = json.dumps({"passed": False, "issues": ["Phát hiện khung hình đen"]})

    caps = json.dumps(
        {
            "facebook": {"text": "FB text", "hashtags": ["#fb"]},
            "instagram": {"text": "IG text", "hashtags": ["#ig"]},
            "threads": {"text": "TH text", "hashtags": ["#th"]},
            "tiktok": {"text": "TT text", "hashtags": ["#tt"]},
            "youtube": {"text": "YT text", "hashtags": ["#yt"]},
        },
        ensure_ascii=False,
    )

    with get_conn(paths.db_file) as conn:
        # 1: strict_footage with unverified claims -> blocked on approve
        conn.execute(
            """
            INSERT INTO videos (id, workspace_id, status, output_path, plan_json, captions_json, unsupported_claims_json, preflight_json, qc_json, quality_score)
            VALUES (1, ?, 'pending_approval', ?, ?, ?, '["Chống nước tuyệt đối 100m"]', ?, ?, 9.0)
            """,
            (ws_strict, master_rel, '{"title": "Video Claim Lỗi"}', caps, preflight_ok, qc_ok),
        )
        # 2 & 3: strict_footage valid -> bulk_approve creates non-colliding slots on acc_strict only
        for vid in (2, 3):
            conn.execute(
                """
                INSERT INTO videos (id, workspace_id, status, output_path, plan_json, captions_json, preflight_json, qc_json, quality_score)
                VALUES (?, ?, 'pending_approval', ?, ?, ?, ?, ?, 8.8)
                """,
                (vid, ws_strict, master_rel, json.dumps({"title": f"Nhẫn Bạc {vid}"}), caps, preflight_ok, qc_ok),
            )
        # 4: autopilot workspace with good QC + score 8.5 -> auto-scheduled to acc_auto_yt only
        conn.execute(
            """
            INSERT INTO videos (id, workspace_id, status, output_path, plan_json, captions_json, preflight_json, qc_json, quality_score)
            VALUES (4, ?, 'pending_approval', ?, ?, ?, ?, ?, 8.5)
            """,
            (ws_auto, master_rel, '{"title": "Tin Nhanh 24h"}', caps, preflight_ok, qc_ok),
        )
        # 5: autopilot workspace with failed QC -> stays pending_approval
        conn.execute(
            """
            INSERT INTO videos (id, workspace_id, status, output_path, plan_json, captions_json, preflight_json, qc_json, quality_score)
            VALUES (5, ?, 'pending_approval', ?, ?, ?, ?, ?, 9.2)
            """,
            (ws_auto, master_rel, '{"title": "QC Fail"}', caps, preflight_ok, qc_bad),
        )

    # strict_footage blocks unverified claim under policy enforcement
    with pytest.raises(ValueError, match="strict_footage"):
        approve(paths.db_file, 1, by="ui", config_file=paths.config_file, enforce_policy=True)

    # Publish Pack ZIP contains MP4, titled cover, 5-platform captions.txt, and metadata.json
    zip_path = build_publish_pack_zip(paths, 2, cover_title="NHẪN BẠC S925")
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        assert {"video_2.mp4", "cover_2.jpg", "captions.txt", "metadata.json"}.issubset(names)
        cap_txt = zf.read("captions.txt").decode("utf-8")
        for header in ("--- FACEBOOK ---", "--- INSTAGRAM ---", "--- THREADS ---", "--- TIKTOK ---", "--- YOUTUBE ---"):
            assert header in cap_txt
        meta_obj = json.loads(zf.read("metadata.json").decode("utf-8"))
        assert meta_obj["video_id"] == 2
        assert meta_obj["workspace_id"] == ws_strict
        assert "youtube" in meta_obj["captions"]

    # bulk_approve approves #2 and #3 while reporting error on #1, scheduling unique slots on acc_strict only
    now_dt = datetime(2026, 11, 24, 1, 0, 0, tzinfo=timezone.utc)
    bulk_res = bulk_approve(
        paths.db_file,
        [1, 2, 3],
        by="ui",
        config_file=paths.config_file,
        now_dt=now_dt,
    )
    assert bulk_res["approved_ids"] == [2, 3]
    assert "1" in bulk_res["errors"]
    strict_posts = query_all(
        paths.db_file,
        "SELECT account_id, scheduled_at FROM posts WHERE video_id IN (2, 3) ORDER BY scheduled_at ASC",
    )
    assert len(strict_posts) == 2
    assert all(p["account_id"] == acc_strict for p in strict_posts)
    assert strict_posts[0]["scheduled_at"] != strict_posts[1]["scheduled_at"]

    # Autopilot: video #5 (failed QC) rejected; video #4 auto-scheduled ONLY to acc_auto_yt
    assert try_autopilot_approve(paths, 5, now_dt=now_dt) is False
    assert query_one(paths.db_file, "SELECT status FROM videos WHERE id = 5")["status"] == "pending_approval"

    assert try_autopilot_approve(paths, 4, now_dt=now_dt) is True
    assert query_one(paths.db_file, "SELECT status FROM videos WHERE id = 4")["status"] == "scheduled"
    auto_posts = query_all(paths.db_file, "SELECT account_id FROM posts WHERE video_id = 4")
    assert [p["account_id"] for p in auto_posts] == [acc_auto_yt]
