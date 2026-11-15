"""Apify-backed trend sources: mappers on real actor output, budget rule, source selection.

Samples `tests/samples/apify_*.json` are the real dataset items of runs made on 2026-11-14 with the
owner's Apify account (3–9 items each). No mocks; the only network test is opt-in (RUN_LIVE_APIFY).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import query_all
from videocreator.paths import AppPaths
from videocreator.trends.ad_library import MetaAdLibrarySource
from videocreator.trends.apify import (
    APIFY_TOKEN_KEY,
    ApifyFacebookReelsSource,
    ApifyMetaAdsSource,
    ApifyTikTokSource,
)
from videocreator.trends.apify_client import check_budget
from videocreator.trends.apify_mappers import (
    facebook_reels_url,
    map_facebook_reel,
    map_instagram,
    map_meta_ad,
    map_tiktok,
    meta_ads_library_url,
)
from videocreator.trends.apify_watch import normalize_apify_watch
from videocreator.trends.base import WatchItem
from videocreator.trends.rank import score_trend_item
from videocreator.trends.scan import build_trend_sources

SAMPLES = Path(__file__).parent / "samples"
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def _load(name: str) -> list[dict]:
    return json.loads((SAMPLES / f"apify_{name}.json").read_text(encoding="utf-8"))


TIKTOK, IG_HASHTAG, IG_REELS, FB_REELS, FB_ADS = (
    _load("tiktok"), _load("ig_hashtag"), _load("ig_reels"), _load("fb_reels"), _load("fb_ads")
)


@pytest.mark.local
def test_map_real_tiktok_items() -> None:
    items = [map_tiktok(i) for i in TIKTOK]
    assert all(items) and len(items) == len(TIKTOK) == 9
    first, raw = items[0], TIKTOK[0]
    assert first.source == "tiktok"
    assert first.external_id == raw["id"]
    assert first.url == raw["webVideoUrl"]
    assert first.author == raw["authorMeta"]["name"]
    assert first.metrics["views"] == raw["playCount"]
    assert first.metrics["likes"] == raw["diggCount"]
    assert first.metrics["comments"] == raw["commentCount"]
    assert first.metrics["shares"] == raw["shareCount"]
    assert first.metrics["saves"] == raw["collectCount"]
    assert first.published_at == datetime.fromisoformat(raw["createTimeISO"].replace("Z", "+00:00"))
    assert score_trend_item(first, now_dt=NOW) > 0
    assert map_tiktok({**raw, "isSlideshow": True}) is None  # photo slideshows are not videos


@pytest.mark.local
def test_map_real_instagram_reels() -> None:
    tagged = [map_instagram(i, source="ig_hashtag") for i in IG_HASHTAG]
    reels = [map_instagram(i, source="ig_discovery") for i in IG_REELS]
    assert all(tagged) and all(reels)
    assert tagged[0].metrics["views"] == IG_HASHTAG[0]["videoPlayCount"]
    assert reels[0].author == "tiffanyandco"
    assert reels[0].external_id == IG_REELS[0]["shortCode"]
    assert reels[0].metrics["likes"] == IG_REELS[0]["likesCount"]
    assert map_instagram({**IG_REELS[0], "type": "Image"}, source="ig_discovery") is None


@pytest.mark.local
def test_map_real_facebook_reels() -> None:
    items = [map_facebook_reel(i) for i in FB_REELS]
    assert all(items) and len(items) == 6
    first, raw = items[0], FB_REELS[0]
    assert first.url == raw["shareable_url"]
    assert first.external_id == raw["shareable_url"].rsplit("/", 1)[1]
    assert first.author == raw["video_owner"]["name"]
    assert first.metrics["views"] == raw["playCountRounded"]
    assert first.metrics["duration_s"] == round(raw["video"]["playable_duration_in_ms"] / 1000, 2)


@pytest.mark.local
def test_map_real_meta_ads_keeps_only_video_ads() -> None:
    mapped = [map_meta_ad(i, now_dt=NOW) for i in FB_ADS]
    with_video = [i for i in FB_ADS if (i.get("snapshot") or {}).get("videos")]
    kept = [m for m in mapped if m]
    assert len(kept) == len(with_video) >= 1
    ad, raw = kept[0], with_video[0]
    assert ad.source == "ad_library"
    assert ad.url == f"https://www.facebook.com/ads/library/?id={raw['adArchiveID']}"
    assert ad.author == raw["pageName"]
    started = datetime.fromtimestamp(int(raw["startDate"]), tz=timezone.utc)
    assert ad.metrics["days_running"] == round((NOW - started).total_seconds() / 86400, 1)
    assert ad.metrics["is_active"] is True
    assert score_trend_item(ad, now_dt=NOW) > 0  # running > 30 days


@pytest.mark.local
def test_budget_rule_stops_before_the_cap() -> None:
    assert check_budget(0.0, 5.0, 5.0) is None
    stop = check_budget(4.6, 5.0, 5.0)
    assert stop is not None and "giới hạn" in stop  # scan.py stops the source for this scan
    assert check_budget(4.6, 5.0, 20.0) is not None  # the account's own $5 limit still applies
    assert check_budget(4.6, 20.0, 20.0) is None
    assert check_budget(19.6, 20.0, 20.0) is not None


@pytest.mark.local
@pytest.mark.parametrize(
    ("source", "kind", "raw", "expected"),
    [
        ("tiktok", "account", "@TiffanyAndCo", "TiffanyAndCo"),
        ("tiktok", "account", "https://www.tiktok.com/@tiffanyandco?lang=en", "tiffanyandco"),
        ("tiktok", "hashtag", "#silverjewelry", "silverjewelry"),
        ("tiktok", "keyword", "nhẫn bạc handmade", "nhẫn bạc handmade"),
        ("ig_discovery", "account", "https://www.instagram.com/tiffanyandco/", "tiffanyandco"),
        ("ig_hashtag", "hashtag", "#silver925", "silver925"),
        ("facebook", "page", "https://www.facebook.com/pandora/reels/", "https://www.facebook.com/pandora"),
        ("ad_library", "page", "https://www.facebook.com/ads/library/?view_all_page_id=637837956391837&x=1", "637837956391837"),
        ("ad_library", "keyword", "trang sức bạc", "trang sức bạc"),
    ],
)
def test_normalize_apify_watch(source: str, kind: str, raw: str, expected: str) -> None:
    assert normalize_apify_watch(source, kind, raw) == expected


@pytest.mark.local
@pytest.mark.parametrize(
    ("source", "kind", "raw"),
    [
        ("tiktok", "account", "https://www.youtube.com/@x"),
        ("tiktok", "hashtag", "bad tag!"),
        ("ad_library", "page", "not a page"),
        ("tiktok", "keyword", "   "),
    ],
)
def test_normalize_apify_watch_rejects(source: str, kind: str, raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_apify_watch(source, kind, raw)


@pytest.mark.local
def test_urls_sent_to_the_actors() -> None:
    url = meta_ads_library_url("keyword", "trang sức bạc", "vn")
    assert "country=VN" in url and "media_type=video" in url and "q=trang%20s%E1%BB%A9c%20b%E1%BA%A1c" in url
    assert "view_all_page_id=637837956391837" in meta_ads_library_url("page", "637837956391837", "VN")
    assert facebook_reels_url("https://www.facebook.com/pandora") == "https://www.facebook.com/pandora/reels/"
    assert facebook_reels_url("https://www.facebook.com/profile.php?id=1") == "https://www.facebook.com/profile.php?id=1&sk=reels_tab"


@pytest.mark.local
def test_token_switches_sources_and_watchlist_accepts_tiktok(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths: AppPaths = app.state.paths
    sec = app.state.secrets
    assert isinstance(build_trend_sources(paths, sec)["ad_library"], MetaAdLibrarySource)
    assert "tiktok" not in build_trend_sources(paths, sec)

    # Only the presence of the key matters for source selection; no call is made with it here.
    sec.set(APIFY_TOKEN_KEY, "placeholder-for-source-selection")
    srcs = build_trend_sources(paths, sec)
    assert isinstance(srcs["tiktok"], ApifyTikTokSource)
    assert isinstance(srcs["facebook"], ApifyFacebookReelsSource)
    assert isinstance(srcs["ad_library"], ApifyMetaAdsSource)
    assert srcs["facebook"].status() == (True, None)

    with TestClient(app) as client:
        client.post("/watchlist/add", data={"source": "tiktok", "kind": "hashtag", "value": "#silverjewelry"})
        client.post("/watchlist/add", data={"source": "facebook", "kind": "page", "value": "https://www.facebook.com/pandora/reels/"})
        r = client.post("/watchlist/add", data={"source": "tiktok", "kind": "page", "value": "x"}, follow_redirects=True)
        assert "chỉ nhận loại" in r.text
    rows = query_all(paths.db_file, "SELECT source, kind, value FROM watch_items ORDER BY id")
    assert rows == [
        {"source": "tiktok", "kind": "hashtag", "value": "silverjewelry"},
        {"source": "facebook", "kind": "page", "value": "https://www.facebook.com/pandora"},
    ]


@pytest.mark.live
def test_apify_tiktok_keyword_live(tmp_path: Path) -> None:
    """Real run on the owner's Apify account (about $0.02). Needs RUN_LIVE_APIFY=1."""
    if not os.environ.get("RUN_LIVE_APIFY"):
        pytest.skip("RUN_LIVE_APIFY not set (spends Apify credit)")
    from videocreator.paths import get_paths
    from videocreator.secrets_store import SecretsStore

    real = SecretsStore(get_paths().secrets_file).get(APIFY_TOKEN_KEY)
    if not real:
        pytest.skip("APIFY_API_TOKEN not in the app's secrets store")
    app = create_app(data_dir=tmp_path, start_worker=False)
    app.state.secrets.set(APIFY_TOKEN_KEY, real)
    cfg_paths: AppPaths = app.state.paths
    from videocreator.config import load_settings, save_settings

    cfg = load_settings(cfg_paths.config_file)
    cfg.trends.apify_results_per_item = 3
    cfg.trends.lookback_days = 365
    save_settings(cfg_paths.config_file, cfg)

    items = ApifyTikTokSource(cfg_paths, app.state.secrets).fetch(WatchItem(1, "tiktok", "keyword", "nhẫn bạc handmade"))
    assert items and all(i.source == "tiktok" and i.metrics["views"] >= 0 for i in items)
