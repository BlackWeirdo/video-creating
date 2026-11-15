"""Meta Ad Library API trend source for long-running EU video ads (>= 30 days, Phase 12)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.posting.meta_auth import GRAPH_BASE_URL
from videocreator.secrets_store import SecretsStore
from videocreator.trends.base import TrendItem, WatchItem


class MetaAdLibrarySource:
    name = "ad_library"
    kinds = ("keyword", "page")

    def __init__(
        self,
        paths: AppPaths,
        secrets_store: SecretsStore | None = None,
        *,
        http_client: Any = None,
    ) -> None:
        self.paths = paths
        self.secrets = secrets_store or SecretsStore(paths.secrets_file)
        self._http_client = http_client

    def status(self) -> tuple[bool, str | None]:
        if not self.secrets.has("META_AD_LIBRARY_TOKEN"):
            return False, "chưa bật: thiếu META_AD_LIBRARY_TOKEN (cần xác minh danh tính Meta Ad Library)"
        return True, None

    def fetch(self, watch: WatchItem) -> list[TrendItem]:
        ok, reason = self.status()
        if not ok:
            raise RuntimeError(reason or "Ad Library disabled")

        token = self.secrets.get("META_AD_LIBRARY_TOKEN") or ""
        cfg = load_settings(self.paths.config_file)
        countries = cfg.trends.ad_library_countries or ["DE", "FR", "IT", "ES", "NL"]

        params: dict[str, Any] = {
            "ad_reached_countries": json.dumps(countries),
            "ad_active_status": "ALL",
            "media_type": "VIDEO",
            "fields": "id,page_name,ad_creative_bodies,ad_delivery_start_time,ad_delivery_stop_time,eu_total_reach,ad_snapshot_url",
            "limit": 25,
            "access_token": token,
        }
        if watch.kind == "page":
            params["search_page_ids"] = json.dumps([watch.value.strip()])
        else:
            params["search_terms"] = watch.value.strip()

        own_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=30.0)
        try:
            resp = client.get(f"{GRAPH_BASE_URL}/ads_archive", params=params)
            resp.raise_for_status()
            ads = (resp.json() or {}).get("data") or []
            now_utc = datetime.now(timezone.utc)
            items = (_ad_to_trend_item(ad, now_utc) for ad in ads)
            return [item for item in items if item is not None]
        finally:
            if own_client:
                client.close()


MIN_DAYS_RUNNING = 30.0


def _parse_utc(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _ad_to_trend_item(ad: dict[str, Any], now_utc: datetime) -> TrendItem | None:
    """A video ad that ran for at least 30 days; None for anything else."""
    ad_id = str(ad.get("id") or "")
    start_str = str(ad.get("ad_delivery_start_time") or "")
    if not ad_id or not start_str:
        return None
    start_dt = _parse_utc(start_str)
    if start_dt is None:
        return None

    stop_str = str(ad.get("ad_delivery_stop_time") or "")
    stop_dt = _parse_utc(stop_str) if stop_str else None
    is_active = stop_dt is None
    end_dt = stop_dt or now_utc

    days_running = max(0.0, (end_dt - start_dt).total_seconds() / 86400.0)
    if days_running < MIN_DAYS_RUNNING:
        return None

    bodies = ad.get("ad_creative_bodies") or []
    snap_url = str(ad.get("ad_snapshot_url") or f"https://www.facebook.com/ads/library/?id={ad_id}")
    return TrendItem(
        source="ad_library",
        external_id=ad_id,
        url=snap_url,
        author=str(ad.get("page_name") or ""),
        caption="\n".join(str(b) for b in bodies)[:1000],
        published_at=start_dt,
        metrics={
            "days_running": round(days_running, 1),
            "is_active": is_active,
            "eu_reach": int(ad.get("eu_total_reach") or 1),
        },
        video_url=snap_url,
    )
