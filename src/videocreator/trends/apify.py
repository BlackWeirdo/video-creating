"""Apify-backed trend sources: TikTok, Instagram Reels, Facebook Reels, Meta Ad Library (all countries).

Owner decision 2026-11-14 (changes `BR-REF-04` for trend data): trend data may come from a
third-party scraping service. One `APIFY_API_TOKEN` drives five adapters that keep the existing
source names (`tiktok`, `ig_hashtag`, `ig_discovery`, `facebook`, `ad_library`), so the watchlist,
scoring, analysis and suggestions work unchanged. Without the token the official adapters stay.

Actors and field mappings were checked against real runs on 2026-11-14
(`tests/samples/apify_*.json`). Spend is capped twice: the account's monthly usage is read before
every run and compared with `trends.apify_monthly_usd`, and each run carries `maxTotalChargeUsd`.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.trends.apify_client import ApifyClient, ApifyError, check_budget
from videocreator.trends.apify_mappers import (
    facebook_reels_url,
    map_facebook_reel,
    map_instagram,
    map_meta_ad,
    map_tiktok,
    meta_ads_library_url,
)
from videocreator.trends.base import TrendItem, WatchItem

logger = logging.getLogger("videocreator.trends.apify")

APIFY_TOKEN_KEY = "APIFY_API_TOKEN"

ACTOR_TIKTOK = "clockworks~tiktok-scraper"
ACTOR_IG_HASHTAG = "apify~instagram-hashtag-scraper"
ACTOR_IG_REELS = "apify~instagram-reel-scraper"
ACTOR_FB_REELS = "apify~facebook-reels-scraper"
ACTOR_META_ADS = "apify~facebook-ads-scraper"


# ---------- HTTP client ----------


# ---------- value normalisation ----------


# ---------- mappers (pure, tested on real samples) ----------


# ---------- adapters ----------

class _ApifySource:
    name = ""
    kinds: tuple[str, ...] = ()

    def __init__(
        self,
        paths: AppPaths,
        secrets_store: SecretsStore | None = None,
        *,
        client_factory: Callable[[str], ApifyClient] | None = None,
    ) -> None:
        self.paths = paths
        self.secrets = secrets_store or SecretsStore(paths.secrets_file)
        self._client_factory = client_factory or ApifyClient

    def status(self) -> tuple[bool, str | None]:
        if not self.secrets.has(APIFY_TOKEN_KEY):
            return False, "chưa bật: thiếu APIFY_API_TOKEN trong Cài đặt"
        return True, None

    def _build_actor_input(self, watch: WatchItem, limit: int) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    def _map_item(self, item: dict[str, Any], watch: WatchItem) -> TrendItem | None:
        raise NotImplementedError

    def fetch(self, watch: WatchItem) -> list[TrendItem]:
        ok, reason = self.status()
        if not ok:
            raise ApifyError(reason or "Apify chưa bật")
        cfg = load_settings(self.paths.config_file)
        client = self._client_factory(self.secrets.get(APIFY_TOKEN_KEY) or "")
        used, limit = client.monthly_usage()
        stop = check_budget(used, limit, cfg.trends.apify_monthly_usd)
        if stop:
            raise ApifyError(stop)
        n = max(1, min(50, cfg.trends.apify_results_per_item))
        actor, run_input = self._build_actor_input(watch, n)
        items, cost = client.run_actor(actor, run_input, max_items=n)
        logger.info("Apify %s for %s/%s: %d items, $%.4f", actor, watch.kind, watch.value, len(items), cost)
        for it in items:
            # "no_items" = nothing matched (normal, e.g. no video ads for a keyword).
            # Other errors (e.g. "not_available": page private or wrong name) concern this watch item only.
            if it.get("error") and it.get("error") != "no_items":
                raise RuntimeError(f"Apify ({watch.value}): {it.get('errorDescription') or it.get('error')}")
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, cfg.trends.lookback_days))
        out = []
        for it in items:
            ti = self._map_item(it, watch)
            if ti is not None and (self.name == "ad_library" or ti.published_at >= cutoff):
                out.append(ti)
        return out


class ApifyTikTokSource(_ApifySource):
    name = "tiktok"
    kinds = ("keyword", "hashtag", "account")

    def _build_actor_input(self, watch: WatchItem, limit: int) -> tuple[str, dict[str, Any]]:
        key = {"keyword": "searchQueries", "hashtag": "hashtags", "account": "profiles"}[watch.kind]
        extra: dict[str, Any] = {}
        if watch.kind == "keyword":
            # TikTok's "Top" search returns popular but old videos, which the lookback filter then
            # drops (1 of 10 survived on 2026-11-14). Search videos of the lookback window instead.
            lookback = load_settings(self.paths.config_file).trends.lookback_days
            extra = {
                "searchSection": "/video",
                "videoSearchSorting": "MOST_RELEVANT",
                "videoSearchDateFilter": "PAST_MONTH" if lookback <= 31 else "LAST_3_MONTHS",
            }
        return ACTOR_TIKTOK, {
            key: [watch.value],
            **extra,
            "resultsPerPage": limit,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
            "shouldDownloadSlideshowImages": False,
            "shouldDownloadAvatars": False,
            "shouldDownloadMusicCovers": False,
        }

    def _map_item(self, item: dict[str, Any], watch: WatchItem) -> TrendItem | None:
        return map_tiktok(item)


class ApifyInstagramHashtagSource(_ApifySource):
    name = "ig_hashtag"
    kinds = ("hashtag",)

    def _build_actor_input(self, watch: WatchItem, limit: int) -> tuple[str, dict[str, Any]]:
        return ACTOR_IG_HASHTAG, {"hashtags": [watch.value], "resultsType": "reels", "resultsLimit": limit}

    def _map_item(self, item: dict[str, Any], watch: WatchItem) -> TrendItem | None:
        return map_instagram(item, source=self.name)


class ApifyInstagramAccountSource(_ApifySource):
    name = "ig_discovery"
    kinds = ("account",)

    def _build_actor_input(self, watch: WatchItem, limit: int) -> tuple[str, dict[str, Any]]:
        return ACTOR_IG_REELS, {"username": [watch.value], "resultsLimit": limit}

    def _map_item(self, item: dict[str, Any], watch: WatchItem) -> TrendItem | None:
        return map_instagram(item, source=self.name)


class ApifyFacebookReelsSource(_ApifySource):
    name = "facebook"
    kinds = ("page", "account")

    def _build_actor_input(self, watch: WatchItem, limit: int) -> tuple[str, dict[str, Any]]:
        return ACTOR_FB_REELS, {"startUrls": [{"url": facebook_reels_url(watch.value)}], "resultsLimit": limit}

    def _map_item(self, item: dict[str, Any], watch: WatchItem) -> TrendItem | None:
        return map_facebook_reel(item)


class ApifyMetaAdsSource(_ApifySource):
    name = "ad_library"
    kinds = ("keyword", "page")

    def _build_actor_input(self, watch: WatchItem, limit: int) -> tuple[str, dict[str, Any]]:
        country = load_settings(self.paths.config_file).trends.ads_country
        return ACTOR_META_ADS, {
            "startUrls": [{"url": meta_ads_library_url(watch.kind, watch.value, country)}],
            "resultsLimit": limit,
        }

    def _map_item(self, item: dict[str, Any], watch: WatchItem) -> TrendItem | None:
        return map_meta_ad(item)


APIFY_SOURCE_CLASSES = (
    ApifyTikTokSource,
    ApifyInstagramHashtagSource,
    ApifyInstagramAccountSource,
    ApifyFacebookReelsSource,
    ApifyMetaAdsSource,
)
