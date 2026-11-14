"""Local SQLite-backed tests for 24h/72h/7d checkpoint collection and weekly summary (Phase 15)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from videocreator.db import get_conn, migrate, query_all
from videocreator.paths import get_paths
from videocreator.posting.base import Account
from videocreator.posting.metrics import (
    _default_metrics_reader,
    collect_due_metrics,
    due_checkpoints,
    list_performance_rows,
)
from videocreator.reports import weekly_summary
from videocreator.secrets_store import SecretsStore


class _RecordedMetricsAdapter:
    """Deterministic adapter returning recorded platform insights payload."""

    def __init__(self, payload_by_post_id: dict[str, dict[str, int | None]]) -> None:
        self.payload_by_post_id = payload_by_post_id

    def fetch_metrics(self, account: Account, external_post_id: str) -> dict[str, int | None]:
        return self.payload_by_post_id.get(
            external_post_id,
            {"views": None, "likes": None, "comments": None, "shares": None},
        )


@pytest.mark.local
def test_due_checkpoints_window_and_24h_expiry() -> None:
    posted_at = "2026-11-10T10:00:00Z"

    # 12h after posting -> not yet 24h
    assert due_checkpoints(posted_at, datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc), set()) == []

    # 25h after posting -> 24h is due
    assert due_checkpoints(posted_at, datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc), set()) == ["24h"]

    # Already has 24h -> not due again
    assert due_checkpoints(posted_at, datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc), {"24h"}) == []

    # 50h after posting (> 24h + 24h retry window) -> 24h skipped, 72h not yet due
    assert due_checkpoints(posted_at, datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc), set()) == []

    # 74h after posting -> 72h is due
    assert due_checkpoints(posted_at, datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc), {"24h"}) == ["72h"]

    # 170h after posting -> 7d is due
    assert due_checkpoints(posted_at, datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc), {"24h", "72h"}) == ["7d"]


@pytest.mark.local
def test_collect_due_metrics_and_weekly_summary_aggregation(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO accounts (id, platform, external_id, name, lang, secret_key, enabled)
            VALUES (1, 'facebook', 'fb_1', 'FB Trang sức', 'vi', 'META_1', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO trend_items (id, source, external_id, url, author, caption, published_at, score)
            VALUES (1, 'youtube', 'yt_1', 'https://youtube.com/watch?v=1', 'Brand', 'Cap', '2026-11-09T00:00:00Z', 80.0)
            """
        )
        conn.execute(
            """
            INSERT INTO suggestions (id, trend_item_id, text, formula_json, status)
            VALUES (10, 1, 'Đề xuất nhẫn bạc', '{"formula":"hook-first"}', 'accepted')
            """
        )
        # Video 1: hook-first, from suggestion #10
        conn.execute(
            """
            INSERT INTO videos (id, status, plan_json, suggestion_id)
            VALUES (1, 'posted', '{"title":"Nhẫn Bạc Xoắn","formula":"hook-first"}', 10)
            """
        )
        # Video 2: process-story, regular (no suggestion)
        conn.execute(
            """
            INSERT INTO videos (id, status, plan_json, suggestion_id)
            VALUES (2, 'posted', '{"title":"Chế tác Dây chuyền","formula":"process-story"}', NULL)
            """
        )
        conn.execute(
            """
            INSERT INTO posts (id, video_id, account_id, status, scheduled_at, external_post_id, permalink, posted_at)
            VALUES
              (101, 1, 1, 'posted', '2026-11-10T10:00:00Z', 'fb_post_101', 'https://fb.com/101', '2026-11-10T10:00:00Z'),
              (102, 2, 1, 'posted', '2026-11-10T10:00:00Z', 'fb_post_102', 'https://fb.com/102', '2026-11-10T10:00:00Z')
            """
        )

    adapter = _RecordedMetricsAdapter(
        {
            "fb_post_101": {"views": 4200, "likes": 310, "comments": 28, "shares": None},
            "fb_post_102": {"views": 1800, "likes": 95, "comments": 9, "shares": 4},
        }
    )

    # At 73h after posting -> collects 72h checkpoint for both posts
    now_73h = datetime(2026, 11, 13, 11, 0, tzinfo=timezone.utc)
    count_1 = collect_due_metrics(
        paths,
        now_dt=now_73h,
        reader_overrides={"facebook": adapter},
    )
    assert count_1 == 2

    # Second tick at same time does not duplicate
    count_2 = collect_due_metrics(
        paths,
        now_dt=now_73h,
        reader_overrides={"facebook": adapter},
    )
    assert count_2 == 0

    rows = query_all(paths.db_file, "SELECT * FROM post_metrics ORDER BY post_id ASC")
    assert len(rows) == 2
    # Missing shares on post 101 stays None (never fake 0)
    assert rows[0]["views"] == 4200
    assert rows[0]["shares"] is None

    perf_rows = list_performance_rows(paths.db_file)
    assert len(perf_rows) == 2

    report = weekly_summary(paths, now_dt=now_73h)
    assert "hook-first" in report
    assert "process-story" in report
    assert "4200" in report
    assert "Đề xuất xu hướng=4200 (n=1)" in report
    assert "Thường=1800 (n=1)" in report

    # Verify _default_metrics_reader instantiates all 4 platform posters with (paths, secrets)
    secrets = SecretsStore(paths.secrets_file)
    for plat in ("facebook", "instagram", "threads", "tiktok"):
        reader = _default_metrics_reader(plat, secrets, paths)
        assert reader is not None
        assert hasattr(reader, "fetch_metrics")
