"""Regression tests for security hardening, replan distinctness, Studio sandbox, posting idempotency, and UI/Telegram state sync (no mocks)."""
from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from videocreator.ai.base import AIError, ProviderAuthError
from videocreator.ai.retry import call_api_with_retry
from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_all, query_one
from videocreator.job_store import wake_expired_quota_jobs
from videocreator.paths import get_paths
from videocreator.pipeline.plan_schema import (
    FactCheckResult,
    PlannedShot,
    PlatformCaption,
    PlatformCaptions,
    RemixPlansBatch,
    VideoPlanItem,
)
from videocreator.pipeline.render_batch import enqueue_batch_render
from videocreator.pipeline.replan import replan_video
from videocreator.posting import instagram, instagram_graph, tiktok
from videocreator.posting.base import PendingPostError
from videocreator.posting.captions import format_platform_caption
from videocreator.redo import redo_video
from videocreator.reports import weekly_summary
from videocreator.secrets_store import SecretsStore
from videocreator.studio.agent import run_studio_job
from videocreator.studio.session import create_studio_session, request_studio_revision
from videocreator.tg.callbacks import route_callback
from videocreator.tg.pending_input import _update_caption

SAMPLE_CLIP = Path(__file__).resolve().parent / "samples" / "clip1_6s.mp4"


@pytest.mark.local
def test_localhost_passwordless_csrf_protection_and_settings_validation(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        # Passwordless GET and same-origin POST on localhost succeed
        assert client.get("/settings").status_code == 200
        same_origin = client.post(
            "/trends/scan",
            headers={"Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin"},
            follow_redirects=False,
        )
        assert same_origin.status_code == 303

        # Cross-site browser requests are rejected with 403
        cross_fetch = client.post(
            "/trends/scan",
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert cross_fetch.status_code == 403

        cross_origin = client.post(
            "/trends/scan",
            headers={"Origin": "https://evil.example"},
            follow_redirects=False,
        )
        assert cross_origin.status_code == 403

        null_origin = client.post(
            "/trends/scan",
            headers={"Origin": "null"},
            follow_redirects=False,
        )
        assert null_origin.status_code == 403

        bad_referer = client.post(
            "/trends/scan",
            headers={"Referer": "https://evil.example/attack.html"},
            follow_redirects=False,
        )
        assert bad_referer.status_code == 403

        # Non-integer Telegram IDs return 400 instead of crashing with 500
        bad_cfg = client.post(
            "/settings/config",
            data={"allowed_chat_ids": "not_an_int"},
            headers={"Origin": "http://127.0.0.1:8765"},
            follow_redirects=False,
        )
        assert bad_cfg.status_code == 400


class _IdenticalPlanWriter:
    """Writer stand-in that always proposes the exact same shot set [1, 2] as the parent video."""

    def generate_json(self, prompt: str, schema: type[RemixPlansBatch]) -> RemixPlansBatch:
        cap = PlatformCaption(text="Nhẫn bạc S925", hashtags=["#bac925"])
        return RemixPlansBatch(
            plans=[
                VideoPlanItem(
                    formula="hook-first",
                    title="Kịch bản trùng lặp",
                    shots=[
                        PlannedShot(shot_id=1, start_s=0.0, duration_s=3.0, text="Mở đầu"),
                        PlannedShot(shot_id=2, start_s=3.0, duration_s=3.0, text="Cận cảnh"),
                    ],
                    captions=PlatformCaptions(facebook=cap, instagram=cap, threads=cap, tiktok=cap),
                )
            ]
        )


class _CleanChecker:
    def generate_json(self, prompt: str, schema: type[FactCheckResult]) -> FactCheckResult:
        return FactCheckResult(unverified_claims=[])


@pytest.mark.local
def test_replan_refuses_identical_script_on_human_redo_and_auto_retry(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    old_plan = {
        "formula": "hook-first",
        "title": "Bản gốc",
        "total_duration_s": 6.0,
        "shots": [
            {"shot_id": 1, "start_s": 0.0, "duration_s": 3.0, "text": "Mở đầu"},
            {"shot_id": 2, "start_s": 3.0, "duration_s": 3.0, "text": "Cận cảnh"},
        ],
    }
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, status)
            VALUES (1, 'footage/1.mp4', 'sha_replan_1', 6.0, 1080, 1920, 'portrait', 'analysed')
            """
        )
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, quality)
            VALUES
              (1, 1, 1, 0.0, 3.0, 'Shot 1', '["product"]', 1, 5),
              (2, 1, 2, 3.0, 6.0, 'Shot 2', '["product"]', 1, 5)
            """
        )
        conn.execute(
            """
            INSERT INTO videos (id, footage_id, status, plan_json, captions_json, quality_score, quality_notes)
            VALUES
              (10, 1, 'pending_approval', ?, '{}', 8.2, 'Đạt chuẩn'),
              (20, 1, 'rendered', ?, '{}', 6.5, 'Mở đầu hơi chậm')
            """,
            (json.dumps(old_plan, ensure_ascii=False), json.dumps(old_plan, ensure_ascii=False)),
        )

    # 1. Human redo: cannot generate a distinct script -> marks replacement 'failed', queues NO render
    v_human_redo = redo_video(paths.db_file, 10, by="ui")
    assert v_human_redo is not None
    msg_human = replan_video(
        paths,
        v_human_redo,
        writer_provider=_IdenticalPlanWriter(),
        checker_provider=_CleanChecker(),
    )
    assert "Không thể làm lại" in msg_human
    redo_row = query_one(paths.db_file, "SELECT status, error, quality_notes FROM videos WHERE id = ?", (v_human_redo,))
    assert redo_row is not None
    assert redo_row["status"] == "failed"
    assert "Không thể làm lại" in str(redo_row["error"] or "")
    assert query_all(paths.db_file, "SELECT * FROM jobs WHERE kind = 'render'") == []

    # 2. Automatic quality retry: cannot generate a distinct script -> restores parent (#20) to pending_approval
    v_auto_redo = redo_video(paths.db_file, 20, by="auto_quality", is_auto_retry=True)
    assert v_auto_redo is not None
    msg_auto = replan_video(
        paths,
        v_auto_redo,
        writer_provider=_IdenticalPlanWriter(),
        checker_provider=_CleanChecker(),
    )
    assert "Không thể tự làm lại" in msg_auto
    child_row = query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (v_auto_redo,))
    parent_row = query_one(paths.db_file, "SELECT status, quality_notes FROM videos WHERE id = 20")
    assert child_row is not None and child_row["status"] == "superseded"
    assert parent_row is not None and parent_row["status"] == "pending_approval"
    assert "Không thể tự làm lại" in str(parent_row["quality_notes"] or "")
    assert query_all(paths.db_file, "SELECT * FROM jobs WHERE kind = 'render'") == []


@pytest.mark.local
def test_studio_sandbox_detaches_node_modules_records_cost_and_protects_approved_video(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    rel_ftg = "footage/clip1_6s.mp4"
    abs_ftg = paths.media_dir / rel_ftg
    abs_ftg.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAMPLE_CLIP, abs_ftg)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, status)
            VALUES (1, ?, 'sha_st_fix', 6.0, 1080, 1920, 'portrait', 'analysed')
            """,
            (rel_ftg,),
        )
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, quality)
            VALUES (1, 1, 1, 0.0, 3.0, 'Shot sản phẩm', '["product"]', 1, 5)
            """
        )

    observed_node_modules: list[bool] = []

    def _planning_agent(proj_dir: Path, prompt: str, attempt: int, resume_ref: str | None) -> tuple[str, float]:
        nm = proj_dir / "node_modules"
        observed_node_modules.append(nm.exists() or nm.is_symlink())
        (proj_dir / "plan.json").write_text(
            json.dumps(
                {"title": "Studio Test", "scenes": [{"shot_id": 1, "start_s": 0.0, "duration_s": 3.0, "text": "Nhẫn bạc"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return "sess_cost_1", 0.42

    sid = create_studio_session(paths, prompt="Tạo kịch bản Studio")
    # Batch FFmpeg render must never pick up Studio videos
    assert enqueue_batch_render(paths.db_file) == []

    res = run_studio_job(paths, sid, code_generator=_planning_agent, checker_provider=_CleanChecker())
    assert res["status"] == "awaiting_confirm"
    assert observed_node_modules == [False]
    sess_row = query_one(paths.db_file, "SELECT cost_usd, video_id FROM studio_sessions WHERE id = ?", (sid,))
    assert sess_row is not None
    assert abs(float(sess_row["cost_usd"]) - 0.42) < 1e-6

    # Once the linked video is approved, Studio revision must refuse to overwrite it
    vid = int(sess_row["video_id"])
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE studio_sessions SET status = 'done' WHERE id = ?", (sid,))
        conn.execute("UPDATE videos SET status = 'approved' WHERE id = ?", (vid,))
    with pytest.raises(ValueError, match="đã được duyệt"):
        request_studio_revision(paths, sid, "Sửa đè lên video đã duyệt")

    # When an unrendered Studio session fails, its 'planned' video row transitions to 'failed'
    sid_fail = create_studio_session(paths, prompt="Phiên lỗi")

    def _failing_agent(proj_dir: Path, prompt: str, attempt: int, resume_ref: str | None) -> tuple[str, float]:
        raise RuntimeError("Agent crashed")

    with pytest.raises(RuntimeError, match="Agent crashed"):
        run_studio_job(paths, sid_fail, code_generator=_failing_agent, checker_provider=_CleanChecker())
    fail_sess = query_one(paths.db_file, "SELECT status, video_id FROM studio_sessions WHERE id = ?", (sid_fail,))
    assert fail_sess is not None and fail_sess["status"] == "failed"
    fail_vid = query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (fail_sess["video_id"],))
    assert fail_vid is not None and fail_vid["status"] == "failed"


@pytest.mark.local
def test_tiktok_publish_resume_and_instagram_expired_container_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state: dict[str, Any] = {
        "tiktok_uploads": 0,
        "tiktok_ready": False,
        "ig_created": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            _ = self.rfile.read(length)
            state["tiktok_uploads"] += 1
            self.send_response(201)
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/graph/c_expired":
                return self._json({"status_code": "EXPIRED"})
            if url.path == "/graph/c_fresh":
                return self._json({"status_code": "FINISHED"})
            if url.path == "/graph/ig_media_99":
                return self._json({"permalink": "https://www.instagram.com/reel/ig_media_99/"})
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            url = urlparse(self.path)
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            if url.path == "/tiktok/post/publish/creator_info/query/":
                return self._json({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE"]}, "error": {"code": "ok"}})
            if url.path == "/tiktok/post/publish/video/init/":
                return self._json(
                    {
                        "data": {"publish_id": "tt_pub_1", "upload_url": f"{base}/tiktok/upload"},
                        "error": {"code": "ok"},
                    }
                )
            if url.path == "/tiktok/post/publish/status/fetch/":
                if state["tiktok_ready"]:
                    return self._json(
                        {
                            "data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ["778899"]},
                            "error": {"code": "ok"},
                        }
                    )
                return self._json({"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok"}})
            if url.path == "/graph/ig_1/media":
                state["ig_created"] += 1
                return self._json({"id": "c_fresh"})
            if url.path == "/graph/ig_1/media_publish":
                form = parse_qs(raw.decode("utf-8"))
                assert form.get("creation_id") == ["c_fresh"]
                return self._json({"id": "ig_media_99"})
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        monkeypatch.setattr(tiktok, "TIKTOK_API_BASE", f"{base_url}/tiktok")
        monkeypatch.setattr(tiktok, "MAX_POLLS", 2)
        monkeypatch.setattr(tiktok, "POLL_SLEEP_S", 0.0)
        monkeypatch.setattr(instagram, "GRAPH_BASE_URL", f"{base_url}/graph")
        monkeypatch.setattr(instagram_graph, "GRAPH_BASE_URL", f"{base_url}/graph")

        paths = get_paths(tmp_path)
        migrate(paths.db_file)
        cfg = load_settings(paths.config_file)
        cfg.tiktok.mode = "direct"
        save_settings(paths.config_file, cfg)

        secrets = SecretsStore(paths.secrets_file)
        secrets.set("TT_TOK", "tiktok-secret-token")
        secrets.set("IG_TOK", "ig-secret-token")

        video_file = paths.media_dir / "output" / "video_1.mp4"
        video_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SAMPLE_CLIP, video_file)

        with get_conn(paths.db_file) as conn:
            conn.execute("INSERT INTO videos (id, status, plan_json) VALUES (1, 'scheduled', '{}')")
            conn.execute(
                """
                INSERT INTO accounts (id, platform, external_id, name, lang, secret_key, enabled)
                VALUES
                  (1, 'tiktok', 'tt_u1', 'silver_shop', 'vi', 'TT_TOK', 1),
                  (2, 'instagram', 'ig_1', 'IG Shop', 'vi', 'IG_TOK', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO posts (id, video_id, account_id, status, scheduled_at, remote_container_id)
                VALUES
                  (1, 1, 1, 'publishing', '2026-11-15T10:00:00Z', NULL),
                  (2, 1, 2, 'publishing', '2026-11-15T10:00:00Z', 'c_expired')
                """
            )

        # TikTok attempt 1: uploads once, saves publish_id, raises PendingPostError while processing
        tt_poster = tiktok.TikTokPoster(paths, secrets)
        tt_acc = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = 1")
        tt_post = query_one(paths.db_file, "SELECT * FROM posts WHERE id = 1")
        assert tt_acc is not None and tt_post is not None
        with pytest.raises(PendingPostError):
            tt_poster.publish(tt_acc, None, video_file, "Nhẫn bạc S925", tt_post)

        tt_saved = query_one(paths.db_file, "SELECT * FROM posts WHERE id = 1")
        assert tt_saved is not None and tt_saved["remote_container_id"] == "tt_pub_1"
        assert state["tiktok_uploads"] == 1

        # TikTok attempt 2: resumes status polling without re-uploading bytes
        state["tiktok_ready"] = True
        tt_res = tt_poster.publish(tt_acc, None, video_file, "Nhẫn bạc S925", tt_saved)
        assert tt_res.status == "posted"
        assert tt_res.external_post_id == "778899"
        assert state["tiktok_uploads"] == 1

        # Instagram: expired container 'c_expired' is discarded and replaced with 'c_fresh'
        ig_poster = instagram.InstagramReelsPoster(paths, secrets, poll_interval_s=0.0)
        ig_acc = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = 2")
        ig_post = query_one(paths.db_file, "SELECT * FROM posts WHERE id = 2")
        assert ig_acc is not None and ig_post is not None
        ig_res = ig_poster.publish(ig_acc, f"{base_url}/v.mp4", video_file, "Nhẫn bạc S925", ig_post)
        assert ig_res.status == "posted"
        assert ig_res.external_post_id == "ig_media_99"
        assert state["ig_created"] == 1
        ig_saved = query_one(paths.db_file, "SELECT remote_container_id FROM posts WHERE id = 2")
        assert ig_saved is not None and ig_saved["remote_container_id"] == "c_fresh"
    finally:
        server.shutdown()


@pytest.mark.local
def test_wake_expired_quota_jobs_text_timestamp_and_retry_classification(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "INSERT INTO provider_state (name, resting_until) VALUES ('claude_cli', '100')"
        )
        conn.execute(
            "INSERT INTO jobs (id, kind, ref_id, status) VALUES (1, 'plan', 1, 'waiting_quota')"
        )

    assert wake_expired_quota_jobs(paths.db_file) == 1
    j_row = query_one(paths.db_file, "SELECT status FROM jobs WHERE id = 1")
    assert j_row is not None and j_row["status"] == "queued"

    # Numeric token counts like 4012 must not trigger HTTP 401 ProviderAuthError
    with pytest.raises(AIError) as exc_info:
        call_api_with_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("Processed 4012 prompt tokens before unexpected EOF")),
            provider="claude_api",
            label="Claude API",
            auth_markers=("401", "403", "unauthorized"),
            quota_markers=("429",),
            quota_label="rate limited",
            server_codes=("500",),
        )
    assert not isinstance(exc_info.value, ProviderAuthError)

    with pytest.raises(ProviderAuthError):
        call_api_with_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("HTTP 401: invalid key")),
            provider="claude_api",
            label="Claude API",
            auth_markers=("401", "403", "unauthorized"),
            quota_markers=("429",),
            quota_label="rate limited",
            server_codes=("500",),
        )


@pytest.mark.local
def test_caption_sync_account_slots_roundtrip_weekly_report_and_tg_empty_approvers(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths
    cfg = load_settings(paths.config_file)
    cfg.telegram.allowed_chat_ids = [-100555]
    cfg.telegram.approver_user_ids = []  # Empty approver list must fail closed for mutating callbacks
    save_settings(paths.config_file, cfg)

    plan_with_4_caps = {
        "title": "Video 4 nền tảng",
        "formula": "hook-first",
        "shots": [],
        "captions": {
            "facebook": {"text": "FB gốc", "hashtags": ["#fb"]},
            "instagram": {"text": "IG gốc", "hashtags": ["#ig"]},
            "threads": {"text": "TH gốc", "hashtags": ["#th"]},
            "tiktok": {"text": "TT gốc", "hashtags": ["#tt"]},
        },
    }
    now_dt = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    old_iso = (now_dt - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent_iso = (now_dt - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, status, plan_json, captions_json)
            VALUES
              (1, 'pending_approval', ?, '{}'),
              (2, 'posted', '{"title":"Bài cũ","formula":"craft-process","shots":[]}', '{}')
            """,
            (json.dumps(plan_with_4_caps, ensure_ascii=False),),
        )
        conn.execute(
            """
            INSERT INTO accounts (id, platform, external_id, name, lang, secret_key, enabled)
            VALUES (1, 'facebook', 'fb_1', 'FB Shop', 'vi', 'FB_SEC', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO posts (id, video_id, account_id, status, scheduled_at, posted_at)
            VALUES
              (1, 2, 1, 'posted', ?, ?),
              (2, 1, 1, 'posted', ?, ?)
            """,
            (old_iso, old_iso, recent_iso, recent_iso),
        )
        conn.execute(
            """
            INSERT INTO post_metrics (post_id, checkpoint, views, likes, comments, shares)
            VALUES
              (1, '72h', 99999, 100, 10, 5),
              (2, '72h', 450, 20, 2, 1)
            """
        )

    # 1. Telegram empty approver_user_ids fails closed on mutating callback, allows read-only cmd:status
    allowed_mut, msg_mut, won_mut, _ = route_callback(
        paths, chat_id=-100555, user_id=777, user_name="Guest", data="ok:1", now_dt=now_dt
    )
    assert allowed_mut is False and won_mut is False
    assert "approver_user_ids" in msg_mut

    allowed_ro, _msg_ro, _won_ro, _ = route_callback(
        paths, chat_id=-100555, user_id=777, user_name="Guest", data="cmd:status", now_dt=now_dt
    )
    assert allowed_ro is True

    # 2. Editing Threads caption via Telegram preserves Facebook, Instagram, and TikTok captions
    _update_caption(paths.db_file, cfg, 1, "threads", "TH mới từ Telegram", "tg:101:Admin")
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = 1")
    assert v_row is not None
    assert "TH mới từ Telegram" in format_platform_caption(v_row, "threads")
    assert "FB gốc" in format_platform_caption(v_row, "facebook")
    assert "IG gốc" in format_platform_caption(v_row, "instagram")
    assert "TT gốc" in format_platform_caption(v_row, "tiktok")

    # 3. Account slots UI value round-trips cleanly across multiple saves
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        r1 = client.post(
            "/accounts/1/slots",
            data={"slots": "09:00, 18:30"},
            headers={"Origin": "http://127.0.0.1:8765"},
            follow_redirects=False,
        )
        assert r1.status_code == 303
        page = client.get("/accounts")
        assert 'value="09:00, 18:30"' in page.text

        # Second save submitting the rendered input value keeps the exact same JSON array
        r2 = client.post(
            "/accounts/1/slots",
            data={"slots": "09:00, 18:30"},
            headers={"Origin": "http://127.0.0.1:8765"},
            follow_redirects=False,
        )
        assert r2.status_code == 303
        acc_row = query_one(paths.db_file, "SELECT slots_json FROM accounts WHERE id = 1")
        assert acc_row is not None
        assert json.loads(str(acc_row["slots_json"])) == ["09:00", "18:30"]

        # Detail page /videos/1 reflects the Telegram Threads caption edit AND keeps FB caption
        vid_page = client.get("/videos/1")
        assert "TH mới từ Telegram" in vid_page.text
        assert "FB gốc" in vid_page.text

    # 4. Weekly summary only includes 72h metrics from posts within the last 7 days
    report_txt = weekly_summary(paths, now_dt=now_dt)
    assert "450 lượt xem" in report_txt
    assert "99999" not in report_txt
