"""Instagram Reels 2-step container + publish adapter (Phase 07, FR-PST-05)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from videocreator.db import get_conn
from videocreator.paths import AppPaths
from videocreator.posting.base import (
    MetricsFetchError,
    PermanentPostError,
    PostResult,
    TransientPostError,
    check_preflight_or_raise,
    empty_metrics,
    metrics_http_outcome,
)
from videocreator.posting.instagram_graph import fetch_reel_insights, fetch_reel_permalink, graph_request
from videocreator.posting.meta_auth import GRAPH_BASE_URL
from videocreator.posting.meta_published import find_recent_post, instagram_recent_media, unconfirmed_result
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
        check_preflight_or_raise(self.paths.config_file, video_path, "instagram")

        token = self.secrets.get(str(account["secret_key"]))
        if not token:
            raise PermanentPostError(
                f"Missing Instagram access token in secrets store (key={account['secret_key']})"
            )

        ig_id = str(account["external_id"])
        post_id = int(post["id"])
        # Step 1: Reuse saved container unless it expired/errored before publishing (FR-PST-05)
        container_id = str(post.get("remote_container_id") or "").strip()
        if container_id:
            initial_code = self._peek_container_status(container_id, token)
            if initial_code in ("ERROR", "EXPIRED"):
                container_id = ""
        if not container_id:
            container_id = self._create_container(ig_id, token, video_url, caption, post_id=post_id)
        if self._wait_until_finished(container_id, token) == "PUBLISHED":
            # An earlier attempt published it but its reply was lost: find the post, never publish twice
            try:
                found = find_recent_post(instagram_recent_media(ig_id, token), caption, post.get("scheduled_at"))
            except Exception:  # the post IS published: whatever fails now, a person confirms it
                found = None
            if found is None:
                return unconfirmed_result(container_id)
            return PostResult(
                status="posted",
                external_post_id=str(found.get("id") or ""),
                permalink=str(found.get("permalink") or "") or None,
            )

        # Step 3: Publish container
        published = graph_request(
            "POST",
            f"{GRAPH_BASE_URL}/{ig_id}/media_publish",
            token,
            error_label="Instagram publish network error",
            data={"creation_id": container_id},
            timeout=60.0,
        )
        media_id = str(published.get("id") or "")
        return PostResult(
            status="posted",
            external_post_id=media_id,
            permalink=fetch_reel_permalink(media_id, token),
        )

    def _peek_container_status(self, container_id: str, token: str) -> str:
        try:
            status = graph_request(
                "GET",
                f"{GRAPH_BASE_URL}/{container_id}",
                token,
                error_label="Instagram status check network error",
                params={"fields": "status_code"},
                timeout=30.0,
            )
            return str(status.get("status_code") or "").upper()
        except PermanentPostError:
            return "EXPIRED"

    def _create_container(self, ig_id: str, token: str, video_url: str, caption: str, *, post_id: int) -> str:
        """Creates the Reels container and saves its id on the post so a retry reuses it."""
        created = graph_request(
            "POST",
            f"{GRAPH_BASE_URL}/{ig_id}/media",
            token,
            error_label="Instagram container network error",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true",
            },
            timeout=60.0,
        )
        container_id = str(created.get("id") or "").strip()
        if not container_id:
            raise TransientPostError(f"Instagram returned no container id: {created}")
        with get_conn(self.paths.db_file) as conn:
            conn.execute(
                "UPDATE posts SET remote_container_id = ? WHERE id = ?",
                (container_id, post_id),
            )
        return container_id

    def _wait_until_finished(self, container_id: str, token: str) -> str:
        """Step 2: polls the container `status_code` until FINISHED (or PUBLISHED); returns it."""
        for _ in range(self.max_polls):
            status = graph_request(
                "GET",
                f"{GRAPH_BASE_URL}/{container_id}",
                token,
                error_label="Instagram status poll network error",
                params={"fields": "status_code,status"},
                timeout=30.0,
            )
            status_code = str(status.get("status_code") or "").upper()
            if status_code in ("FINISHED", "PUBLISHED"):
                return status_code
            if status_code in ("ERROR", "EXPIRED"):
                raise PermanentPostError(
                    f"Instagram container {container_id} failed ({status_code}): {status.get('status')}"
                )
            time.sleep(self.poll_interval_s)
        raise TransientPostError(
            f"Instagram container {container_id} still processing after polling window; will retry"
        )

    def fetch_metrics(
        self, account: dict[str, Any], external_post_id: str
    ) -> dict[str, int | None]:
        token = self.secrets.get(str(account["secret_key"]))
        if not token or not external_post_id:
            raise MetricsFetchError(f"Instagram metrics: missing token or post id (account #{account.get('id')})")
        try:
            resp = httpx.get(
                f"{GRAPH_BASE_URL}/{external_post_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "like_count,comments_count"},
                timeout=20.0,
            )
            if resp.status_code != 200:
                err_body = resp.json() if resp.content else None
                metrics_http_outcome(resp.status_code, "Instagram metrics", err_body)
                return empty_metrics()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MetricsFetchError(f"Instagram metrics: {exc}") from exc
        likes = data.get("like_count")
        comments = data.get("comments_count")
        insights = fetch_reel_insights(external_post_id, token)
        return {
            "views": insights.get("views"),
            "likes": int(likes) if likes is not None else None,
            "comments": int(comments) if comments is not None else None,
            "shares": insights.get("shares"),
        }
