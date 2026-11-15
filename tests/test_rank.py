"""Real SQLite tests for trend scoring, deduplicated upsert, quota tracking, and disabled source reporting (Phase 12)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import query_all
from videocreator.trends.base import TrendItem
from videocreator.trends.ig_hashtag import check_and_record_hashtag_quota
from videocreator.trends.rank import score_trend_item
from videocreator.trends.scan import scan_all, upsert_trend_item

SAMPLES_FILE = Path(__file__).parent / "samples" / "trend_items.json"


@pytest.mark.local
def test_score_trend_items_and_upsert_without_duplicates(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    raw_items = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
    now_utc = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)

    parsed_items: list[TrendItem] = []
    for r in raw_items:
        pub_dt = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
        it = TrendItem(
            source=r["source"],
            external_id=r["external_id"],
            url=r["url"],
            author=r["author"],
            caption=r["caption"],
            published_at=pub_dt,
            metrics=r["metrics"],
            video_url=r.get("video_url"),
        )
        parsed_items.append(it)

    # 1. Verify within-source scoring order
    s_yt1 = score_trend_item(parsed_items[0], now_dt=now_utc)
    s_yt2 = score_trend_item(parsed_items[1], now_dt=now_utc)
    assert s_yt1 > s_yt2 > 0

    s_ad = score_trend_item(parsed_items[2], now_dt=now_utc)
    # 50 * 1.5 + log10(100000) = 75 + 5 = 80.0
    assert s_ad == 80.0

    # 2. Upsert twice -> no duplicates created
    for it in parsed_items:
        upsert_trend_item(paths.db_file, it, now_dt=now_utc)
    for it in parsed_items:
        upsert_trend_item(paths.db_file, it, now_dt=now_utc)

    rows = query_all(paths.db_file, "SELECT * FROM trend_items ORDER BY score DESC")
    assert len(rows) == 3

    # 3. 30 hashtags / 7 days quota guard
    for i in range(30):
        ok, count = check_and_record_hashtag_quota(paths.db_file, f"#silver_{i}", now_dt=now_utc)
        assert ok is True
        assert count == i + 1
    # Re-querying an already-searched hashtag within 7 days is still allowed
    ok_repeat, _ = check_and_record_hashtag_quota(paths.db_file, "#silver_0", now_dt=now_utc)
    assert ok_repeat is True
    # 31st distinct hashtag in 7 days is blocked
    ok_31, _ = check_and_record_hashtag_quota(paths.db_file, "#silver_new_31", now_dt=now_utc)
    assert ok_31 is False


@pytest.mark.local
def test_watchlist_ui_and_disabled_source_does_not_break_scan(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    with TestClient(app) as client:
        r1 = client.post(
            "/watchlist/add",
            data={"source": "youtube", "kind": "keyword", "value": "handcrafted silver ring"},
            follow_redirects=True,
        )
        assert r1.status_code == 200
        assert "handcrafted silver ring" in r1.text
        assert "chưa bật: thiếu YOUTUBE_API_KEY" in r1.text

        r2 = client.post(
            "/watchlist/add",
            data={"source": "ad_library", "kind": "keyword", "value": "sterling silver"},
            follow_redirects=True,
        )
        assert r2.status_code == 200

    # Running scan_all when ad_library is missing token does not crash and records reason cleanly
    scan_res = scan_all(paths)
    assert "youtube" in scan_res["errors"]
    assert "ad_library" in scan_res["errors"]
    assert "chưa bật" in scan_res["errors"]["ad_library"]
