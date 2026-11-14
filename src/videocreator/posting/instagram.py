"""Instagram Reels 2-step container + publish adapter (Phase 07, FR-PST-05)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from videocreator.config import load_settings
from videocreator.db import get_conn
from videocreator.paths import AppPaths
from videocreator.pipeline.preflight import check_platform
from videocreator.posting.base import PermanentPostError, PostResult, TransientPostError
from videocreator.posting.meta_auth import GRAPH_BASE_URL, classify_meta_error
from videocreator.secrets_store import SecretsStore


class InstagramReelsPoster:
    platform: str = "instagram"

    def __init__(
        self,
        paths: AppPaths,
        secrets_store: SecretsStore | None = None,
        *,
        poll_interval_s: float = 5.0,
        max_polls: int = 36,
    ) -> None:
        self.paths = paths
        self.secrets = secrets_store or SecretsStore(paths.secrets_file)
        self.poll_interval_s = poll_interval_s
        self.max_polls = max_polls

    def publish(
        self,
        account: dict[str, Any],
        video_url: str,
        video_path: Path,
        caption: str,
        post: dict[str, Any],
    ) -> PostResult:
        settings = load_settings(self.paths.config_file)
        limit = settings.platform_limits.get("instagram")
        if limit is not None:
            pf_errs = check_platform(video_path, "instagram", limit)
            if pf_errs:
                raise PermanentPostError("; ".join(pf_errs))

        token = self.secrets.get(str(account["secret_key"]))
        if not token:
            raise PermanentPostError(
                f"Missing Instagram access token in secrets store (key={account['secret_key']})"
            )

        ig_id = str(account["external_id"])
        post_id = int(post["id"])
        container_id = str(post.get("remote_container_id") or "").strip()

        # Step 1: Create container if not already saved from an earlier attempt (FR-PST-05)
        if not container_id:
            try:
                c_resp = httpx.post(
                    f"{GRAPH_BASE_URL}/{ig_id}/media",
                    headers={"Authorization": f"Bearer {token}"},
                    data={
                        "media_type": "REELS",
                        "video_url": video_url,
                        "caption": caption,
                        "share_to_feed": "true",
                    },
                    timeout=60.0,
                )
            except httpx.RequestError as exc:
                raise TransientPostError(f"Instagram container network error: {exc}") from exc

            try:
                c_data = c_resp.json()
            except Exception:
                c_data = {}

            if c_resp.status_code >= 400:
                raise classify_meta_error(c_resp.status_code, c_data)

            container_id = str(c_data.get("id") or "").strip()
            if not container_id:
                raise TransientPostError(f"Instagram returned no container id: {c_data}")

            with get_conn(self.paths.db_file) as conn:
                conn.execute(
                    "UPDATE posts SET remote_container_id = ? WHERE id = ?",
                    (container_id, post_id),
                )

        # Step 2: Poll container status_code until FINISHED
        finished = False
        for _ in range(self.max_polls):
            try:
                s_resp = httpx.get(
                    f"{GRAPH_BASE_URL}/{container_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"fields": "status_code,status"},
                    timeout=30.0,
                )
            except httpx.RequestError as exc:
                raise TransientPostError(f"Instagram status poll network error: {exc}") from exc

            try:
                s_data = s_resp.json()
            except Exception:
                s_data = {}

            if s_resp.status_code >= 400:
                raise classify_meta_error(s_resp.status_code, s_data)

            status_code = str(s_data.get("status_code") or "").upper()
            if status_code in ("FINISHED", "PUBLISHED"):
                finished = True
                break
            if status_code in ("ERROR", "EXPIRED"):
                raise PermanentPostError(
                    f"Instagram container {container_id} failed ({status_code}): {s_data.get('status')}"
                )
            time.sleep(self.poll_interval_s)

        if not finished:
            raise TransientPostError(
                f"Instagram container {container_id} still processing after polling window; will retry"
            )

        # Step 3: Publish container
        try:
            p_resp = httpx.post(
                f"{GRAPH_BASE_URL}/{ig_id}/media_publish",
                headers={"Authorization": f"Bearer {token}"},
                data={"creation_id": container_id},
                timeout=60.0,
            )
        except httpx.RequestError as exc:
            raise TransientPostError(f"Instagram publish network error: {exc}") from exc

        try:
            p_data = p_resp.json()
        except Exception:
            p_data = {}

        if p_resp.status_code >= 400:
            raise classify_meta_error(p_resp.status_code, p_data)

        media_id = str(p_data.get("id") or "")
        permalink = f"https://www.instagram.com/reel/{media_id}/"
        try:
            link_resp = httpx.get(
                f"{GRAPH_BASE_URL}/{media_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "permalink"},
                timeout=20.0,
            )
            if link_resp.status_code == 200:
                permalink = str(link_resp.json().get("permalink") or permalink)
        except Exception:
            pass

        return PostResult(
            status="posted",
            external_post_id=media_id,
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
                params={"fields": "like_count,comments_count"},
                timeout=20.0,
            )
            if resp.status_code != 200:
                return {"views": None, "likes": None, "comments": None, "shares": None}
            data = resp.json()
            likes = data.get("like_count")
            comments = data.get("comments_count")
            views: int | None = None
            try:
                ins = httpx.get(
                    f"{GRAPH_BASE_URL}/{external_post_id}/insights",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"metric": "views,shares"},  # `plays` was replaced by `views`
                    timeout=20.0,
                )
                shares: int | None = None
                if ins.status_code == 200:
                    for item in ins.json().get("data") or []:
                        vals = item.get("values") or []
                        if vals and isinstance(vals[0].get("value"), int):
                            if item.get("name") == "views":
                                views = int(vals[0]["value"])
                            elif item.get("name") == "shares":
                                shares = int(vals[0]["value"])
            except Exception:
                shares = None
            return {
                "views": views,
                "likes": int(likes) if likes is not None else None,
                "comments": int(comments) if comments is not None else None,
                "shares": shares,
            }
        except Exception:
            return {"views": None, "likes": None, "comments": None, "shares": None}
