"""Real SQLite tests for 7-day reference video cleanup, reference isolation from shots, and atomic suggestion accept/dismiss (Phase 13)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import get_conn, query_all, query_one
from videocreator.trends.download import (
    cleanup_expired_reference_videos,
    fetch_reference_video,
)
from videocreator.trends.suggest import accept_suggestion, dismiss_suggestion

SAMPLE_CLIP = Path(__file__).parent / "samples" / "clip1_6s.mp4"


@pytest.mark.local
def test_reference_video_7_day_cleanup_preserves_rea_dir_and_never_enters_shots(
    tmp_path: Path,
) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO trend_items (id, source, external_id, url, author, caption, published_at, score)
            VALUES (1, 'youtube', 'yt_1', 'https://youtube.com/shorts/yt_1', 'SilverCh', 'Ring', '2026-11-01T00:00:00Z', 50.0)
            """
        )

    t_dl = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)

    def copy_sample(_url: str, dest: Path) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(SAMPLE_CLIP.read_bytes())
        return True

    ref_file = fetch_reference_video(
        paths, 1, downloader_fn=copy_sample, now_dt=t_dl
    )
    assert ref_file is not None and ref_file.exists()

    # Simulate rea-video breakdown directory stored alongside reference video
    rea_dir = paths.media_dir / "reference" / "rea_1"
    rea_dir.mkdir(parents=True, exist_ok=True)
    (rea_dir / "VIDEO.md").write_text("# Breakdown\nHook 0-2s", encoding="utf-8")
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE reference_videos SET rea_dir = 'reference/rea_1' WHERE trend_item_id = 1"
        )

    # Verify shots table is completely empty (reference_videos never enters shots: BR-REF-03)
    assert query_all(paths.db_file, "SELECT * FROM shots") == []

    # After 8 days (> 7 days retention), cleanup deletes the .mp4 file but preserves rea_dir!
    cleaned = cleanup_expired_reference_videos(
        paths, now_dt=t_dl + timedelta(days=8)
    )
    assert cleaned == 1
    assert not ref_file.exists()
    assert (rea_dir / "VIDEO.md").exists()

    ref_row = query_one(
        paths.db_file, "SELECT deleted_at, rea_dir FROM reference_videos WHERE trend_item_id = 1"
    )
    assert ref_row is not None
    assert ref_row["deleted_at"] is not None
    assert ref_row["rea_dir"] == "reference/rea_1"


@pytest.mark.local
def test_accept_and_dismiss_suggestion_idempotency(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO trend_items (id, source, external_id, url, author, caption, published_at, score)
            VALUES (1, 'youtube', 'yt_1', 'https://youtube.com/shorts/yt_1', 'SilverCh', 'Ring', '2026-11-10T00:00:00Z', 50.0)
            """
        )
        conn.execute(
            """
            INSERT INTO suggestions (id, trend_item_id, text, formula_json, status)
            VALUES
                (10, 1, 'Làm video cận cảnh chạm khắc mở đầu 2s', '{"formula":"hook-first"}', 'new'),
                (11, 1, 'Làm video quy trình đánh bóng bạc', '{"formula":"craft-process"}', 'sent')
            """
        )

    # 1. Accept suggestion #10 twice -> only first call enqueues a plan job!
    job1 = accept_suggestion(paths, 10, count=1, actor="tg:1001")
    job2 = accept_suggestion(paths, 10, count=1, actor="tg:1002")
    assert job1 is not None
    assert job2 is None

    s10 = query_one(paths.db_file, "SELECT status FROM suggestions WHERE id = 10")
    assert s10 is not None and s10["status"] == "accepted"

    plan_jobs = query_all(paths.db_file, "SELECT * FROM jobs WHERE kind = 'plan'")
    assert len(plan_jobs) == 1

    # 2. Dismiss suggestion #11 -> status becomes dismissed, subsequent accept returns None
    assert dismiss_suggestion(paths.db_file, 11, actor="ui") is True
    assert dismiss_suggestion(paths.db_file, 11, actor="ui") is False
    assert accept_suggestion(paths, 11, count=1, actor="ui") is None

    s11 = query_one(paths.db_file, "SELECT status FROM suggestions WHERE id = 11")
    assert s11 is not None and s11["status"] == "dismissed"

    # 3. Verify /suggestions UI page renders
    with TestClient(app) as client:
        resp = client.get("/suggestions")
        assert resp.status_code == 200
        assert "Làm video cận cảnh chạm khắc" in resp.text
