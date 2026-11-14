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
            results: list[TrendItem] = []

            for ad in ads:
                ad_id = str(ad.get("id") or "")
                start_str = str(ad.get("ad_delivery_start_time") or "")
                stop_str = str(ad.get("ad_delivery_stop_time") or "")
                if not ad_id or not start_str:
                    continue
                try:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                if stop_str:
                    try:
                        end_dt = datetime.fromisoformat(stop_str.replace("Z", "+00:00"))
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                        is_active = False
                    except Exception:
                        end_dt = now_utc
                        is_active = True
                else:
                    end_dt = now_utc
                    is_active = True

                days_running = max(0.0, (end_dt - start_dt).total_seconds() / 86400.0)
                if days_running < 30.0:
                    continue

                bodies = ad.get("ad_creative_bodies") or []
                caption = "\n".join(str(b) for b in bodies)[:1000]
                snap_url = str(
                    ad.get("ad_snapshot_url")
                    or f"https://www.facebook.com/ads/library/?id={ad_id}"
                )
                eu_reach = int(ad.get("eu_total_reach") or 1)
                results.append(
                    TrendItem(
                        source="ad_library",
                        external_id=ad_id,
                        url=snap_url,
                        author=str(ad.get("page_name") or ""),
                        caption=caption,
                        published_at=start_dt,
                        metrics={
                            "days_running": round(days_running, 1),
                            "is_active": is_active,
                            "eu_reach": eu_reach,
                        },
                        video_url=snap_url,
                    )
                )
            return results
        finally:
            if own_client:
                client.close()
