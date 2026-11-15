"""YouTube Data API v3 Shorts trend source with daily quota guard (Phase 12)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from videocreator.config import load_settings
from videocreator.db import get_conn, query_one
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.timeutil import UTC_ISO_FORMAT
from videocreator.trends.base import TrendItem, WatchItem

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
DAILY_YOUTUBE_QUOTA_LIMIT = 8000  # Reserve margin below 10,000 units/day
SEARCH_COST_UNITS = 100
VIDEOS_COST_UNITS = 1


def get_youtube_quota_used(db_file: Path, day_str: str | None = None) -> int:
    day = day_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = query_one(
        db_file, "SELECT value FROM settings WHERE key = ?", (f"yt_quota:{day}",)
    )
    if row is None:
        return 0
    try:
        return int(row["value"])
    except ValueError:
        return 0


def add_youtube_quota_used(db_file: Path, units: int, day_str: str | None = None) -> int:
    day = day_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cur_used = get_youtube_quota_used(db_file, day) + int(units)
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (f"yt_quota:{day}", str(cur_used)),
        )
    return cur_used


class YouTubeTrendSource:
    name = "youtube"
    kinds = ("keyword", "account")

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
        if not self.secrets.has("YOUTUBE_API_KEY"):
            return False, "chưa bật: thiếu YOUTUBE_API_KEY trong Settings"
        used = get_youtube_quota_used(self.paths.db_file)
        if used + SEARCH_COST_UNITS + VIDEOS_COST_UNITS > DAILY_YOUTUBE_QUOTA_LIMIT:
            return False, f"chưa bật: đã chạm trần quota ngày ({used}/{DAILY_YOUTUBE_QUOTA_LIMIT} units)"
        return True, None

    def fetch(self, watch: WatchItem) -> list[TrendItem]:
        ok, reason = self.status()
        if not ok:
            raise RuntimeError(reason or "YouTube source disabled")

        api_key = self.secrets.get("YOUTUBE_API_KEY") or ""
        cfg = load_settings(self.paths.config_file)
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=max(1, cfg.trends.lookback_days))
        ).strftime(UTC_ISO_FORMAT)

        params: dict[str, Any] = {
            "part": "snippet",
            "type": "video",
            "videoDuration": "short",
            "order": "viewCount",
            "publishedAfter": published_after,
            "maxResults": 15,
            "key": api_key,
        }
        if watch.kind == "account" and watch.value.startswith("UC"):
            params["channelId"] = watch.value.strip()
        else:
            params["q"] = watch.value.strip()

        own_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=30.0)
        try:
            add_youtube_quota_used(self.paths.db_file, SEARCH_COST_UNITS)
            r_search = client.get(f"{YOUTUBE_API_BASE}/search", params=params)
            r_search.raise_for_status()
            s_items = r_search.json().get("items") or []
            video_ids = [
                str((it.get("id") or {}).get("videoId") or "")
                for it in s_items
                if (it.get("id") or {}).get("videoId")
            ]
            if not video_ids:
                return []

            add_youtube_quota_used(self.paths.db_file, VIDEOS_COST_UNITS)
            r_vids = client.get(
                f"{YOUTUBE_API_BASE}/videos",
                params={
                    "part": "snippet,statistics",
                    "id": ",".join(video_ids[:50]),
                    "key": api_key,
                },
            )
            r_vids.raise_for_status()
            v_items = r_vids.json().get("items") or []

            results: list[TrendItem] = []
            for v in v_items:
                vid = str(v.get("id") or "")
                if not vid:
                    continue
                snippet = v.get("snippet") or {}
                stats = v.get("statistics") or {}
                pub_str = str(snippet.get("publishedAt") or "")
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pub_dt = datetime.now(timezone.utc)

                title = str(snippet.get("title") or "").strip()
                desc = str(snippet.get("description") or "").strip()
                caption = f"{title}\n{desc}".strip()[:1000]
                url = f"https://www.youtube.com/shorts/{vid}"
                results.append(
                    TrendItem(
                        source="youtube",
                        external_id=vid,
                        url=url,
                        author=str(snippet.get("channelTitle") or ""),
                        caption=caption,
                        published_at=pub_dt,
                        metrics={
                            "views": int(stats.get("viewCount") or 0),
                            "likes": int(stats.get("likeCount") or 0),
                            "comments": int(stats.get("commentCount") or 0),
                        },
                        video_url=url,
                    )
                )
            return results
        finally:
            if own_client:
                client.close()
