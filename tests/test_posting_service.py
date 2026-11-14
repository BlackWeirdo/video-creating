"""Real SQLite tests for posting service, backoff, multi-account publishing, and manual bundle ZIP (Phase 07)."""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from videocreator.api.routes_posting import upsert_account
from videocreator.app import create_app
from videocreator.db import get_conn, migrate, query_all, query_one
from videocreator.paths import get_paths
from videocreator.posting.base import PermanentPostError, PostResult, TransientPostError
from videocreator.posting.meta_auth import classify_meta_error
from videocreator.posting.service import (
    build_manual_bundle_zip,
    cleanup_staged_r2_objects,
    compute_next_attempt_iso,
    publish_due_posts,
    schedule_approved_video,
)

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CLIP_PORTRAIT = SAMPLES_DIR / "clip1_6s.mp4"


@pytest.mark.local
def test_backoff_and_meta_error_classification() -> None:
    base_dt = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
    assert compute_next_attempt_iso(1, base_dt) == "2026-11-13T12:01:00Z"
    assert compute_next_attempt_iso(2, base_dt) == "2026-11-13T12:05:00Z"
    assert compute_next_attempt_iso(3, base_dt) == "2026-11-13T12:30:00Z"

    err_190 = classify_meta_error(
        400, {"error": {"code": 190, "message": "Invalid OAuth access token"}}
    )
    assert isinstance(err_190, PermanentPostError)

    err_rate = classify_meta_error(
        400, {"error": {"code": 4, "message": "Application request limit reached"}}
    )
    assert isinstance(err_rate, TransientPostError)


@pytest.mark.local
def test_unapproved_video_cannot_be_scheduled_and_approved_publishes_multi_account(
    tmp_path: Path,
) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    acc_fb = upsert_account(
        paths,
        platform="facebook",
        external_id="page_111",
        name="FB Page Bạc",
        access_token="tok_fb_111",
        lang="vi",
    )
    acc_ig = upsert_account(
        paths,
        platform="instagram",
        external_id="ig_222",
        name="IG Bạc",
        access_token="tok_ig_222",
        lang="vi",
    )

    out_video = paths.media_dir / "output" / "video_2.mp4"
    out_video.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CLIP_PORTRAIT, out_video)

    captions = {
        "facebook": {"text": "Caption FB", "hashtags": ["#fb"]},
        "instagram": {"text": "Caption IG", "hashtags": ["#ig"]},
    }
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, status, output_path, captions_json)
            VALUES
                (1, 'pending_approval', 'output/video_1.mp4', '{}'),
                (2, 'approved', 'output/video_2.mp4', ?)
            """,
            (json.dumps(captions),),
        )

    # Unapproved video (#1) cannot create posts (FR-APR-01)
    with pytest.raises(ValueError, match="FR-APR-01"):
        schedule_approved_video(paths.db_file, 1, account_ids=[acc_fb])

    base_dt = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
    sched_iso = base_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    post_ids = schedule_approved_video(
        paths.db_file,
        2,
        account_ids=[acc_fb, acc_ig],
        scheduled_at_iso=sched_iso,
    )
    assert len(post_ids) == 2

    # Duplicate schedule for same (video_id, account_id) creates 0 new posts
    dup_ids = schedule_approved_video(
        paths.db_file,
        2,
        account_ids=[acc_fb, acc_ig],
        scheduled_at_iso=sched_iso,
    )
    assert dup_ids == []

    v2 = query_one(paths.db_file, "SELECT status FROM videos WHERE id = 2")
    assert v2 is not None and v2["status"] == "scheduled"

    r2_calls: list[Path] = []

    class InProcessPoster:
        def __init__(self, platform: str) -> None:
            self.platform = platform
            self.published: list[tuple[str, str]] = []

        def publish(
            self,
            account: dict[str, Any],
            video_url: str,
            video_path: Path,
            caption: str,
            post: dict[str, Any],
        ) -> PostResult:
            self.published.append((str(account["external_id"]), caption))
            return PostResult(
                status="posted",
                external_post_id=f"{self.platform}_{post['id']}",
                permalink=f"https://example.com/{self.platform}/{post['id']}",
            )

    fb_poster = InProcessPoster("facebook")
    ig_poster = InProcessPoster("instagram")

    def fake_r2(vpath: Path) -> tuple[str, str]:
        r2_calls.append(vpath)
        return ("videos/key123.mp4", "https://r2.example.com/videos/key123.mp4")

    processed = publish_due_posts(
        paths,
        poster_overrides={"facebook": fb_poster, "instagram": ig_poster},
        r2_uploader=fake_r2,
        now_dt=base_dt + timedelta(seconds=5),
    )
    assert processed == 2
    assert len(r2_calls) == 1  # Staged to R2 only ONCE for the video!
    assert fb_poster.published == [("page_111", "Caption FB\n\n#fb")]
    assert ig_poster.published == [("ig_222", "Caption IG\n\n#ig")]

    v2_after = query_one(paths.db_file, "SELECT status, r2_key, r2_url FROM videos WHERE id = 2")
    assert v2_after is not None and v2_after["status"] == "posted"
    assert v2_after["r2_key"] == "videos/key123.mp4"
    assert v2_after["r2_url"] == "https://r2.example.com/videos/key123.mp4"

    # R2 cleanup before 24h does not delete
    deleted_early = cleanup_staged_r2_objects(
        paths, now_dt=base_dt + timedelta(hours=12), deleter=lambda _k: True
    )
    assert deleted_early == 0

    # R2 cleanup after >24h deletes and clears r2_key / r2_url (FR-PST-05)
    deleted_keys: list[str] = []
    deleted_25h = cleanup_staged_r2_objects(
        paths,
        now_dt=base_dt + timedelta(hours=25),
        deleter=lambda k: (deleted_keys.append(k) or True),
    )
    assert deleted_25h == 1
    assert deleted_keys == ["videos/key123.mp4"]
    v2_cleaned = query_one(paths.db_file, "SELECT r2_key, r2_url FROM videos WHERE id = 2")
    assert v2_cleaned is not None and v2_cleaned["r2_key"] is None and v2_cleaned["r2_url"] is None


@pytest.mark.local
def test_transient_retry_backoff_and_manual_bundle_zip(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    acc_id = upsert_account(
        paths,
        platform="facebook",
        external_id="page_retry",
        name="FB Retry",
        access_token="tok_retry_secret_999",
    )
    out_video = paths.media_dir / "output" / "video_5.mp4"
    out_video.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CLIP_PORTRAIT, out_video)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, status, output_path, captions_json)
            VALUES (5, 'approved', 'output/video_5.mp4', '{"facebook":{"text":"Hello","hashtags":["#silver"]}}')
            """
        )

    t0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
    schedule_approved_video(
        paths.db_file,
        5,
        account_ids=[acc_id],
        scheduled_at_iso=t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    class FlakyPoster:
        platform = "facebook"

        def __init__(self) -> None:
            self.calls = 0

        def publish(self, account, video_url, video_path, caption, post) -> PostResult:
            self.calls += 1
            if self.calls == 1:
                raise TransientPostError("Temporary network drop")
            return PostResult(
                status="posted",
                external_post_id="fb_ok_5",
                permalink="https://facebook.com/page_retry/videos/fb_ok_5",
            )

    flaky = FlakyPoster()
    r2_fn = lambda p: ("videos/k.mp4", "https://r2.example.com/videos/k.mp4")

    # 1st attempt at t0 -> fails transiently, schedules retry at t0 + 1 min
    publish_due_posts(paths, poster_overrides={"facebook": flaky}, r2_uploader=r2_fn, now_dt=t0)
    post_row = query_all(paths.db_file, "SELECT * FROM posts WHERE video_id = 5")[0]
    assert post_row["status"] == "scheduled"
    assert post_row["attempts"] == 1
    assert post_row["next_attempt_at"] == "2026-11-13T12:01:00Z"

    # Tick at t0 + 30s (before next_attempt_at) -> skipped
    skipped = publish_due_posts(
        paths,
        poster_overrides={"facebook": flaky},
        r2_uploader=r2_fn,
        now_dt=t0 + timedelta(seconds=30),
    )
    assert skipped == 0

    # Tick at t0 + 65s -> succeeds!
    publish_due_posts(
        paths,
        poster_overrides={"facebook": flaky},
        r2_uploader=r2_fn,
        now_dt=t0 + timedelta(seconds=65),
    )
    post_done = query_all(paths.db_file, "SELECT * FROM posts WHERE video_id = 5")[0]
    assert post_done["status"] == "posted"
    assert post_done["permalink"] == "https://facebook.com/page_retry/videos/fb_ok_5"

    # Manual bundle ZIP download
    zip_file = build_manual_bundle_zip(paths, 5)
    assert zip_file.exists()
    with zipfile.ZipFile(zip_file, "r") as zf:
        names = set(zf.namelist())
        assert "video_5.mp4" in names
        assert "captions.txt" in names
        assert "Hello" in zf.read("captions.txt").decode("utf-8")

    with TestClient(app) as client:
        dl = client.get("/videos/5/manual-bundle")
        assert dl.status_code == 200
        assert dl.headers["content-type"] == "application/zip"


@pytest.mark.local
def test_tiktok_chunk_plan_follows_media_transfer_rules() -> None:
    from videocreator.posting.tiktok import plan_chunks

    mb = 1024 * 1024
    assert plan_chunks(4 * mb) == (4 * mb, 1)  # under 5 MB: whole file
    assert plan_chunks(64 * mb) == (64 * mb, 1)
    chunk, total = plan_chunks(100 * mb + 123)  # over 64 MB: split, last chunk absorbs the remainder
    assert (chunk, total) == (32 * mb, 3)
    last_chunk = 100 * mb + 123 - chunk * (total - 1)
    assert 5 * mb <= last_chunk <= 128 * mb
