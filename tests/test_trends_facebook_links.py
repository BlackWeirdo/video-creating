"""Facebook sources, pasted Facebook/Instagram video links, and migration 010.

Real SQLite, real recorded yt-dlp output (`tests/samples/ytdlp_*.json`, read on 2026-11-14 with
the pinned yt-dlp, no login), no mocks. Network is only used by the live test, which is opt-in.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import (
    DEFAULT_MIGRATIONS_DIR,
    get_conn,
    get_setting,
    get_user_version,
    migrate,
    query_all,
    set_setting,
)
from videocreator.paths import AppPaths, get_paths
from videocreator.tg.link_command import handle_link_command
from videocreator.trends.facebook import FACEBOOK_MANUAL_REASON, normalize_facebook_source
from videocreator.trends.link_parse import (
    classify_video_url,
    counts_from_title,
    extract_first_url,
    parse_single_video,
)
from videocreator.trends.links import (
    ANALYSE_TREND_JOB_KIND,
    MAX_PASTED_LINKS_PER_DAY,
    add_pasted_link,
    run_analyse_trend_job,
)
from videocreator.trends.rank import score_trend_item
from videocreator.trends.scan import scan_all, upsert_trend_item
from videocreator.trends.suggest import select_suggestion_candidates

SAMPLES = Path(__file__).parent / "samples"
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def _sample(name: str) -> dict:
    return json.loads((SAMPLES / f"ytdlp_{name}.json").read_text(encoding="utf-8"))


REEL = _sample("facebook_reel")
PAGE_VIDEO = _sample("facebook_page_video")
IG_POST = _sample("instagram_post")


# ---------- Facebook Page / Profile sources ----------

@pytest.mark.local
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.facebook.com/TiffanyAndCo", "https://www.facebook.com/TiffanyAndCo"),
        ("https://m.facebook.com/TiffanyAndCo/reels/?ref=page", "https://www.facebook.com/TiffanyAndCo"),
        ("TiffanyAndCo", "https://www.facebook.com/TiffanyAndCo"),
        ("https://www.facebook.com/profile.php?id=100040874179269&sk=reels", "https://www.facebook.com/profile.php?id=100040874179269"),
        ("https://www.facebook.com/people/Beast-Camp/100040874179269/", "https://www.facebook.com/profile.php?id=100040874179269"),
    ],
)
def test_normalize_facebook_source_accepts_pages_and_profiles(raw: str, expected: str) -> None:
    assert normalize_facebook_source(raw) == expected


@pytest.mark.local
@pytest.mark.parametrize(
    "raw",
    [
        "",
        "https://www.facebook.com/reel/1195289147628387",  # a video: goes to "Thêm video theo link"
        "https://www.facebook.com/watch/?v=647537299265662",
        "https://www.facebook.com/groups/123",
        "https://www.facebook.com/profile.php",
        "https://evil.example/TiffanyAndCo",
        "https://www.facebook.com.evil.io/TiffanyAndCo",
        "reel",
    ],
)
def test_normalize_facebook_source_rejects_non_profile_links(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_facebook_source(raw)


# ---------- Pasted video links ----------

@pytest.mark.local
@pytest.mark.parametrize(
    ("raw", "platform", "clean"),
    [
        ("https://www.facebook.com/reel/1195289147628387", "facebook", "https://www.facebook.com/reel/1195289147628387"),
        ("https://m.facebook.com/reel/1195289147628387/?mibextid=abc", "facebook", "https://www.facebook.com/reel/1195289147628387/"),
        ("https://www.facebook.com/watch/?v=647537299265662&ref=x", "facebook", "https://www.facebook.com/watch/?v=647537299265662"),
        ("https://www.facebook.com/cnn/videos/10155529876156509/", "facebook", "https://www.facebook.com/cnn/videos/10155529876156509/"),
        ("https://www.facebook.com/share/r/1AbCdEf/", "facebook", "https://www.facebook.com/share/r/1AbCdEf/"),
        ("https://fb.watch/abc123/", "facebook", "https://fb.watch/abc123/"),
        ("https://www.instagram.com/reel/C1a2B3c4D5e/?igsh=x", "instagram", "https://www.instagram.com/reel/C1a2B3c4D5e/"),
        ("https://www.instagram.com/p/BQ0eAlwhDrw", "instagram", "https://www.instagram.com/p/BQ0eAlwhDrw"),
    ],
)
def test_classify_video_url_accepts_single_videos(raw: str, platform: str, clean: str) -> None:
    assert classify_video_url(raw) == (platform, clean)


@pytest.mark.local
@pytest.mark.parametrize(
    "raw",
    [
        "https://www.facebook.com/TiffanyAndCo",  # a Page: belongs in the Watchlist
        "https://www.facebook.com/TiffanyAndCo/reels/",
        "https://www.facebook.com/watch/?v=abc",
        "http://www.facebook.com/reel/1195289147628387",
        "https://www.facebook.com.evil.io/reel/1195289147628387",
        "https://evil.io/?u=https://www.facebook.com/reel/1",
        "https://www.instagram.com/instagram/",
        "https://www.youtube.com/shorts/abc",
        "-J https://www.facebook.com/reel/1",
        "file:///C:/Windows/win.ini",
    ],
)
def test_classify_video_url_rejects_everything_else(raw: str) -> None:
    with pytest.raises(ValueError):
        classify_video_url(raw)


@pytest.mark.local
def test_extract_first_url_from_shared_message() -> None:
    shared = "Xem video này nhé https://www.facebook.com/reel/1195289147628387?mibextid=x, hay lắm"
    assert extract_first_url(shared) == "https://www.facebook.com/reel/1195289147628387?mibextid=x"
    assert extract_first_url("không có link") == ""


@pytest.mark.local
def test_counts_from_real_titles() -> None:
    # Only real titles: a Vietnamese-locale title has not been recorded yet, so it is not asserted.
    assert counts_from_title(REEL["title"]) == {"views": 9900, "likes": 340}
    assert counts_from_title(PAGE_VIDEO["title"]) == {}


@pytest.mark.local
def test_parse_real_facebook_reel_uses_title_counts_and_pins() -> None:
    url = "https://www.facebook.com/reel/1195289147628387"
    item = parse_single_video(REEL, platform="facebook", url=url)
    assert item.source == "facebook"
    assert item.external_id == "1195289147628387"
    assert item.url == url
    assert item.author == (REEL.get("channel") or REEL.get("uploader") or "")
    assert item.author
    assert item.published_at == datetime.fromtimestamp(REEL["timestamp"], tz=timezone.utc)
    # yt-dlp's view_count (427) is lower than the count Facebook shows in the title (9.9K).
    assert REEL["view_count"] == 427
    assert item.metrics["views"] == 9900
    assert item.metrics["likes"] == 340
    assert item.metrics["pinned"] is True
    assert item.metrics["duration_s"] == round(REEL["duration"], 2)
    assert item.caption.startswith("When your trying")
    assert score_trend_item(item, now_dt=NOW) > 0


@pytest.mark.local
def test_parse_real_page_video_and_instagram_carousel() -> None:
    page = parse_single_video(PAGE_VIDEO, platform="facebook", url="https://www.facebook.com/cnn/videos/10155529876156509/")
    assert page.external_id == "10155529876156509"
    assert page.metrics["views"] == PAGE_VIDEO["view_count"]
    assert page.author == "CNN"

    ig = parse_single_video(IG_POST, platform="instagram", url="https://www.instagram.com/p/BQ0eAlwhDrw")
    first = IG_POST["entries"][0]
    assert ig.source == "instagram"
    assert ig.external_id == IG_POST["id"]  # the post (what gets downloaded), not the first slide
    assert ig.published_at == datetime.fromtimestamp(first["timestamp"], tz=timezone.utc)
    assert ig.metrics["likes"] == first["like_count"]
    assert ig.metrics["comments"] == first["comment_count"]

    no_video = {**IG_POST, "entries": [{**e, "vcodec": "none", "duration": None} for e in IG_POST["entries"]]}
    with pytest.raises(ValueError, match="không có video"):
        parse_single_video(no_video, platform="instagram", url="https://www.instagram.com/p/x")
    image_only = {k: v for k, v in IG_POST["entries"][0].items() if k not in ("vcodec", "duration")}
    with pytest.raises(ValueError, match="không có video"):
        parse_single_video(image_only, platform="instagram", url="https://www.instagram.com/p/x")


# ---------- Migration 010 ----------

@pytest.mark.local
def test_migration_010_keeps_rows_and_allows_new_sources(tmp_path: Path) -> None:
    old_dir = tmp_path / "mig9"
    old_dir.mkdir()
    for f in sorted(DEFAULT_MIGRATIONS_DIR.glob("*.sql"))[:9]:
        shutil.copy2(f, old_dir / f.name)
    db = tmp_path / "app.db"
    assert migrate(db, migrations_dir=old_dir) == 9

    with get_conn(db) as conn:
        conn.execute("INSERT INTO watch_items (source, kind, value) VALUES ('youtube', 'keyword', 'handcrafted silver ring')")
        conn.execute("INSERT INTO watch_items (source, kind, value, enabled, created_at) VALUES ('ad_library', 'page', '123', 0, '2026-11-01T00:00:00Z')")
        conn.execute("INSERT INTO watch_items (source, kind, value) VALUES ('ig_hashtag', 'hashtag', 'silverjewelry')")
        conn.execute("DELETE FROM watch_items WHERE value = 'silverjewelry'")
    with pytest.raises(sqlite3.IntegrityError):
        with get_conn(db) as conn:
            conn.execute("INSERT INTO watch_items (source, kind, value) VALUES ('facebook', 'page', 'x')")
    before = query_all(db, "SELECT * FROM watch_items ORDER BY id")

    assert migrate(db) == 10
    assert query_all(db, "SELECT * FROM watch_items ORDER BY id") == before
    with get_conn(db) as conn:
        conn.execute("INSERT INTO watch_items (source, kind, value) VALUES ('facebook', 'page', 'https://www.facebook.com/a')")
        conn.execute("INSERT INTO watch_items (source, kind, value) VALUES ('tiktok', 'account', '@a')")
    for bad in [("x", "page", "v"), ("facebook", "page", "https://www.facebook.com/a")]:  # unknown source; duplicate
        with pytest.raises(sqlite3.IntegrityError):
            with get_conn(db) as conn:
                conn.execute("INSERT INTO watch_items (source, kind, value) VALUES (?, ?, ?)", bad)
    after = query_all(db, "SELECT COUNT(*) AS c FROM watch_items")[0]["c"]
    assert migrate(db) == 10  # running again changes nothing
    assert query_all(db, "SELECT COUNT(*) AS c FROM watch_items")[0]["c"] == after
    with get_conn(db) as conn:
        assert get_user_version(conn) == 10
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# ---------- Watchlist + /trends routes ----------

@pytest.mark.local
def test_watchlist_validates_source_kind_and_facebook_links(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths: AppPaths = app.state.paths
    with TestClient(app) as client:
        r = client.post(
            "/watchlist/add",
            data={"source": "facebook", "kind": "page", "value": "https://m.facebook.com/TiffanyAndCo/reels/"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "https://www.facebook.com/TiffanyAndCo" in r.text and "Mở trang" in r.text
        assert "Page Public Content Access" in r.text  # source status explains why it is manual

        r = client.post(
            "/watchlist/add",
            data={"source": "facebook", "kind": "page", "value": "https://www.facebook.com/reel/1195289147628387"},
            follow_redirects=True,
        )
        assert "Thêm video theo link" in r.text
        r = client.post("/watchlist/add", data={"source": "youtube", "kind": "hashtag", "value": "x"}, follow_redirects=True)
        assert "chỉ nhận loại" in r.text
        r = client.post("/watchlist/add", data={"source": "tiktok", "kind": "account", "value": "@a"}, follow_redirects=True)
        assert "không tồn tại" in r.text

    rows = query_all(paths.db_file, "SELECT source, kind, value FROM watch_items")
    assert rows == [{"source": "facebook", "kind": "page", "value": "https://www.facebook.com/TiffanyAndCo"}]

    res = scan_all(paths)  # the manual source never breaks a scan
    assert res["errors"]["facebook"] == FACEBOOK_MANUAL_REASON
    assert res["upserted"] == 0


@pytest.mark.local
def test_add_link_route_rejects_without_network_and_daily_cap(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths: AppPaths = app.state.paths
    with TestClient(app) as client:
        r = client.post("/trends/add-link", data={"url": "https://www.facebook.com/TiffanyAndCo"}, follow_redirects=True)
        assert "Link Fanpage hoặc Profile hãy thêm ở trang Watchlist" in r.text
        assert "Thêm video theo link" in r.text

    day = NOW.strftime("%Y-%m-%d")
    assert get_setting(paths.db_file, f"pasted_links:{day}") is None  # a refused link uses no slot
    set_setting(paths.db_file, f"pasted_links:{day}", str(MAX_PASTED_LINKS_PER_DAY))
    with pytest.raises(ValueError, match="Đã đủ"):
        add_pasted_link(paths, "https://www.facebook.com/reel/1195289147628387", now_dt=NOW)
    assert query_all(paths.db_file, "SELECT id FROM trend_items") == []
    assert query_all(paths.db_file, "SELECT id FROM jobs") == []


@pytest.mark.local
def test_analyse_job_skips_items_already_analysed(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths: AppPaths = app.state.paths
    reel = parse_single_video(REEL, platform="facebook", url="https://www.facebook.com/reel/1195289147628387")
    tid = upsert_trend_item(paths.db_file, reel, now_dt=NOW)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE trend_items SET analysis_json = '{\"hook\": \"h\"}' WHERE id = ?", (tid,))
    assert "already analysed" in run_analyse_trend_job(paths, tid)
    assert "no longer exists" in run_analyse_trend_job(paths, tid + 1)
    assert query_all(paths.db_file, "SELECT id FROM reference_videos") == []


@pytest.mark.local
def test_pinned_items_lead_suggestion_candidates_and_show_badge(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths: AppPaths = app.state.paths
    reel = parse_single_video(REEL, platform="facebook", url="https://www.facebook.com/reel/1195289147628387")
    page = parse_single_video(PAGE_VIDEO, platform="facebook", url="https://www.facebook.com/cnn/videos/10155529876156509/")
    page.metrics.pop("pinned")  # same real video, as if it had come from a scan
    reel_id = upsert_trend_item(paths.db_file, reel, now_dt=NOW)
    page_id = upsert_trend_item(paths.db_file, page, now_dt=NOW)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE trend_items SET analysis_json = '{\"hook\": \"h\"}'")
    scores = {r["id"]: r["score"] for r in query_all(paths.db_file, "SELECT id, score FROM trend_items")}
    assert scores[page_id] > scores[reel_id]  # unpinned scores higher...

    assert [r["id"] for r in select_suggestion_candidates(paths.db_file)] == [reel_id, page_id]  # ...pinned still first

    with TestClient(app) as client:
        html = client.get("/trends?source=facebook").text
    assert "tự chọn" in html


@pytest.mark.local
def test_telegram_link_command_checks_permission_and_input_without_network(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    cfg = load_settings(paths.config_file)
    cfg.telegram.allowed_chat_ids = [-100999888]
    cfg.telegram.approver_user_ids = [101]
    save_settings(paths.config_file, cfg)
    url = "https://www.facebook.com/reel/1195289147628387"

    ok, msg = handle_link_command(paths, chat_id=-100999888, user_id=555, user_name="Lạ", args=url)
    assert ok is False and "quyền" in msg.lower()
    ok, msg = handle_link_command(paths, chat_id=-100999888, user_id=101, user_name="Minh", args="")
    assert ok is False and "/link https://" in msg
    ok, msg = handle_link_command(
        paths, chat_id=-100999888, user_id=101, user_name="Minh", args="https://www.facebook.com/TiffanyAndCo"
    )
    assert ok is False and "Watchlist" in msg
    assert query_all(paths.db_file, "SELECT id FROM trend_items") == []


@pytest.mark.live
def test_add_pasted_facebook_reel_live(tmp_path: Path) -> None:
    if not os.environ.get("RUN_LIVE_FB_LINK"):
        pytest.skip("RUN_LIVE_FB_LINK not set (calls facebook.com)")
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths: AppPaths = app.state.paths

    trend_id, item = add_pasted_link(paths, "https://www.facebook.com/reel/1195289147628387")

    assert item.external_id == "1195289147628387"
    assert item.metrics["views"] > 0 and item.metrics["pinned"] is True
    jobs = query_all(paths.db_file, "SELECT kind, ref_id, status FROM jobs")
    assert jobs == [{"kind": ANALYSE_TREND_JOB_KIND, "ref_id": trend_id, "status": "queued"}]
    again_id, _ = add_pasted_link(paths, "https://m.facebook.com/reel/1195289147628387/")
    assert again_id == trend_id
    assert len(query_all(paths.db_file, "SELECT id FROM trend_items")) == 1
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert get_setting(paths.db_file, f"pasted_links:{day}") == "2"

    # A link that passes the format check but cannot be read uses no daily slot.
    with pytest.raises(ValueError, match="Không đọc được"):
        add_pasted_link(paths, "https://www.facebook.com/reel/1")
    assert get_setting(paths.db_file, f"pasted_links:{day}") == "2"
