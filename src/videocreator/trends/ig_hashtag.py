"""Instagram Hashtag Search trend source with 30-hashtags/7-days rolling quota guard (Phase 12)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from videocreator.db import get_conn, query_one
from videocreator.paths import AppPaths
from videocreator.posting.meta_auth import GRAPH_BASE_URL
from videocreator.secrets_store import SecretsStore
from videocreator.trends.base import TrendItem, WatchItem

MAX_HASHTAGS_PER_7_DAYS = 30


def check_and_record_hashtag_quota(
    db_file: Path, hashtag: str, now_dt: datetime | None = None
) -> tuple[bool, int]:
    """Tracks unique hashtag queries in a rolling 7-day window (max 30 unique hashtags / 7 days)."""
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = base_utc - timedelta(days=7)
    clean_tag = hashtag.strip().lstrip("#").lower()

    row = query_one(db_file, "SELECT value FROM settings WHERE key = 'ig_hashtag_7d'")
    entries: dict[str, str] = {}
    if row and row.get("value"):
        try:
            entries = json.loads(str(row["value"]))
        except Exception:
            entries = {}

    # Prune entries older than 7 days
    active: dict[str, str] = {}
    for tag, iso_str in entries.items():
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            if dt >= cutoff:
                active[tag] = iso_str
        except Exception:
            pass

    if clean_tag not in active and len(active) >= MAX_HASHTAGS_PER_7_DAYS:
        return False, len(active)

    if clean_tag not in active:
        active[clean_tag] = base_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        with get_conn(db_file) as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES ('ig_hashtag_7d', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (json.dumps(active),),
            )
    return True, len(active)


class IGHashtagSource:
    name = "ig_hashtag"
    kinds = ("hashtag",)

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

    def _get_ig_account_and_token(self) -> tuple[str, str] | None:
        row = query_one(
            self.paths.db_file,
            """
            SELECT external_id, secret_key
            FROM accounts
            WHERE platform = 'instagram' AND enabled = 1
            ORDER BY id ASC LIMIT 1
            """,
        )
        if row is None:
            return None
        tok = self.secrets.get(str(row["secret_key"]))
        if not tok:
            return None
        return str(row["external_id"]), tok

    def status(self) -> tuple[bool, str | None]:
        if self._get_ig_account_and_token() is None:
            return False, "chưa bật: chưa kết nối tài khoản Instagram Business"
        return True, None

    def fetch(self, watch: WatchItem) -> list[TrendItem]:
        creds = self._get_ig_account_and_token()
        if creds is None:
            raise RuntimeError("chưa bật: chưa kết nối tài khoản Instagram Business")
        ig_id, token = creds
        tag = watch.value.strip().lstrip("#")

        allowed, used = check_and_record_hashtag_quota(self.paths.db_file, tag)
        if not allowed:
            raise RuntimeError(
                f"Đã chạm giới hạn 30 hashtag / 7 ngày của Instagram ({used}/30)"
            )

        own_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=30.0)
        try:
            r_tag = client.get(
                f"{GRAPH_BASE_URL}/ig_hashtag_search",
                params={"user_id": ig_id, "q": tag, "access_token": token},
            )
            r_tag.raise_for_status()
            tag_data = (r_tag.json() or {}).get("data") or []
            if not tag_data:
                return []
            hashtag_id = str(tag_data[0].get("id") or "")

            r_media = client.get(
                f"{GRAPH_BASE_URL}/{hashtag_id}/top_media",
                params={
                    "user_id": ig_id,
                    "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
                    "access_token": token,
                },
            )
            r_media.raise_for_status()
            media_list = (r_media.json() or {}).get("data") or []
            results: list[TrendItem] = []
            for m in media_list:
                if str(m.get("media_type") or "").upper() != "VIDEO":
                    continue
                mid = str(m.get("id") or "")
                if not mid:
                    continue
                ts = str(m.get("timestamp") or "")
                try:
                    pub_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    pub_dt = datetime.now(timezone.utc)
                permalink = str(m.get("permalink") or f"https://www.instagram.com/p/{mid}/")
                results.append(
                    TrendItem(
                        source="ig_hashtag",
                        external_id=mid,
                        url=permalink,
                        author=f"#{tag}",
                        caption=str(m.get("caption") or "")[:1000],
                        published_at=pub_dt,
                        metrics={
                            "likes": int(m.get("like_count") or 0),
                            "comments": int(m.get("comments_count") or 0),
                            "views": 0,
                        },
                        video_url=permalink,
                    )
                )
            return results
        finally:
            if own_client:
                client.close()
