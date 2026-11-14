"""Instagram Business Discovery trend source (Phase 12)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from videocreator.db import query_one
from videocreator.paths import AppPaths
from videocreator.posting.meta_auth import GRAPH_BASE_URL
from videocreator.secrets_store import SecretsStore
from videocreator.trends.base import TrendItem, WatchItem


class IGBusinessDiscoverySource:
    name = "ig_discovery"
    kinds = ("account",)

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
        creds = self._get_ig_account_and_token()
        if creds is None:
            return False, "chưa bật: chưa kết nối tài khoản Instagram Business"
        return True, None

    def fetch(self, watch: WatchItem) -> list[TrendItem]:
        creds = self._get_ig_account_and_token()
        if creds is None:
            raise RuntimeError("chưa bật: chưa kết nối tài khoản Instagram Business")
        ig_id, token = creds
        handle = watch.value.strip().lstrip("@")

        fields = (
            f"business_discovery.username({handle})"
            "{media.limit(15){id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count}}"
        )
        own_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=30.0)
        try:
            resp = client.get(
                f"{GRAPH_BASE_URL}/{ig_id}",
                params={"fields": fields, "access_token": token},
            )
            resp.raise_for_status()
            bd = (resp.json() or {}).get("business_discovery") or {}
            media_list = (bd.get("media") or {}).get("data") or []
            results: list[TrendItem] = []
            for m in media_list:
                m_type = str(m.get("media_type") or "").upper()
                if m_type not in ("VIDEO", "REELS"):
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
                        source="ig_discovery",
                        external_id=mid,
                        url=permalink,
                        author=handle,
                        caption=str(m.get("caption") or "")[:1000],
                        published_at=pub_dt,
                        metrics={
                            "likes": int(m.get("like_count") or 0),
                            "comments": int(m.get("comments_count") or 0),
                            "views": int(m.get("view_count") or 0),
                        },
                        video_url=permalink,
                    )
                )
            return results
        finally:
            if own_client:
                client.close()
