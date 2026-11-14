"""Facebook Page Reels/Video poster adapter (Phase 07)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.pipeline.preflight import check_platform
from videocreator.posting.base import PermanentPostError, PostResult, TransientPostError
from videocreator.posting.meta_auth import GRAPH_BASE_URL, classify_meta_error
from videocreator.secrets_store import SecretsStore


class FacebookPagePoster:
    platform: str = "facebook"

    def __init__(self, paths: AppPaths, secrets_store: SecretsStore | None = None) -> None:
        self.paths = paths
        self.secrets = secrets_store or SecretsStore(paths.secrets_file)

    def publish(
        self,
        account: dict[str, Any],
        video_url: str,
        video_path: Path,
        caption: str,
        post: dict[str, Any],
    ) -> PostResult:
        settings = load_settings(self.paths.config_file)
        limit = settings.platform_limits.get("facebook")
        if limit is not None:
            pf_errs = check_platform(video_path, "facebook", limit)
            if pf_errs:
                raise PermanentPostError("; ".join(pf_errs))

        token = self.secrets.get(str(account["secret_key"]))
        if not token:
            raise PermanentPostError(
                f"Missing Facebook access token in secrets store (key={account['secret_key']})"
            )

        page_id = str(account["external_id"])
        try:
            resp = httpx.post(
                f"{GRAPH_BASE_URL}/{page_id}/videos",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "file_url": video_url,
                    "description": caption,
                },
                timeout=120.0,
            )
        except httpx.RequestError as exc:
            raise TransientPostError(f"Facebook network error: {exc}") from exc

        try:
            data = resp.json()
        except Exception:
            data = {}

        if resp.status_code >= 400:
            raise classify_meta_error(resp.status_code, data)

        ext_id = str(data.get("id") or "")
        if not ext_id:
            raise TransientPostError(f"Facebook API returned no video id: {data}")

        permalink = f"https://www.facebook.com/{page_id}/videos/{ext_id}"
        return PostResult(
            status="posted",
            external_post_id=ext_id,
            permalink=permalink,
        )

    def fetch_metrics(
        self, account: dict[str, Any], external_post_id: str
    ) -> dict[str, int | None]:
        token = self.secrets.get(str(account["secret_key"]))
        if not token or not external_post_id:
            return {"views": None, "likes": None, "comments": None, "shares": None}
        try:
            resp = httpx.get(
                f"{GRAPH_BASE_URL}/{external_post_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "views,likes.summary(true),comments.summary(true)"},
                timeout=20.0,
            )
            if resp.status_code != 200:
                return {"views": None, "likes": None, "comments": None, "shares": None}
            data = resp.json()
            views = data.get("views")
            likes = ((data.get("likes") or {}).get("summary") or {}).get("total_count")
            comments = ((data.get("comments") or {}).get("summary") or {}).get("total_count")
            return {
                "views": int(views) if views is not None else None,
                "likes": int(likes) if likes is not None else None,
                "comments": int(comments) if comments is not None else None,
                "shares": None,
            }
        except Exception:
            return {"views": None, "likes": None, "comments": None, "shares": None}
