"""Facebook Page Reels poster (Phase 07): start -> upload -> finish, with a status-first retry.

Meta has no idempotency key, so the reel's `video_id` is saved on the post (`remote_container_id`)
right after `start`; every later attempt reads the reel's status first and only does the step
that is still missing. A timed-out `finish` can therefore never publish the reel twice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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
from videocreator.posting.instagram_graph import graph_request
from videocreator.posting.meta_auth import GRAPH_BASE_URL, classify_meta_error
from videocreator.secrets_store import SecretsStore

RUPLOAD_BASE = "https://rupload.facebook.com/video-upload"
UPLOAD_TIMEOUT_S = 300.0
# Saved as `<video_id>#finish_sent` just before `finish`, so an early retry waits for Meta's status
# instead of sending a second finish. After FINISH_RECHECKS failed attempts it is sent again.
FINISH_SENT_MARK = "finish_sent"
FINISH_RECHECKS = 2

ReelStep = Literal["done", "finish", "upload", "restart", "wait"]
_DONE = ("complete", "completed")


def reel_next_step(status_payload: dict[str, Any]) -> ReelStep:
    """What is left to do for a reel, from `GET /{video_id}?fields=status` (pure, testable)."""
    st = status_payload.get("status") or {}
    video_status = str(st.get("video_status") or "").lower()
    upload = str((st.get("uploading_phase") or {}).get("status") or "").lower()
    publishing = st.get("publishing_phase") or {}
    publish_status = str(publishing.get("publish_status") or "").lower()
    publish_phase = str(publishing.get("status") or "").lower()

    if publish_status == "published" or publish_phase in _DONE:
        return "done"
    if video_status in ("error", "expired", "upload_failed") or "error" in (upload, publish_phase):
        return "restart"
    if upload in _DONE:
        return "finish" if publish_phase in ("", "not_started") else "wait"
    if upload in ("", "not_started"):
        return "upload"
    return "wait"


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
        check_preflight_or_raise(self.paths.config_file, video_path, "facebook")

        token = self.secrets.get(str(account["secret_key"]))
        if not token:
            raise PermanentPostError(
                f"Missing Facebook access token in secrets store (key={account['secret_key']})"
            )

        page_id = str(account["external_id"])
        post_id = int(post["id"])
        video_id, _, marker = str(post.get("remote_container_id") or "").strip().partition("#")
        finish_sent = marker == FINISH_SENT_MARK
        if video_id:
            step = reel_next_step(self._status(video_id, token))
        else:
            video_id, step = self._start(page_id, token, post_id), "upload"
        if step == "restart":
            video_id, step, finish_sent = self._start(page_id, token, post_id), "upload", False
        if step == "upload":
            self._upload(video_id, token, video_path)
            step = "finish"
        if step == "finish":
            if finish_sent and int(post.get("attempts") or 0) < FINISH_RECHECKS:
                # A finish was sent and its reply lost; Meta may not show it as published yet.
                raise TransientPostError(f"Facebook reel {video_id}: finish already sent, waiting for Meta to confirm")
            self._save_container(post_id, f"{video_id}#{FINISH_SENT_MARK}")
            self._finish(page_id, token, video_id, caption)
        elif step == "wait":
            raise TransientPostError(f"Facebook reel {video_id} is still uploading or publishing; will check again")
        return PostResult(status="posted", external_post_id=video_id, permalink=self._permalink(video_id, token))

    def _start(self, page_id: str, token: str, post_id: int) -> str:
        """Step 1: creates the reel and saves its id on the post before anything is uploaded."""
        data = graph_request(
            "POST",
            f"{GRAPH_BASE_URL}/{page_id}/video_reels",
            token,
            error_label="Facebook reel start network error",
            data={"upload_phase": "start"},
            timeout=60.0,
        )
        video_id = str(data.get("video_id") or "").strip()
        if not video_id:
            raise TransientPostError(f"Facebook reel start returned no video_id: {data}")
        self._save_container(post_id, video_id)
        return video_id

    def _save_container(self, post_id: int, value: str) -> None:
        with get_conn(self.paths.db_file) as conn:
            conn.execute("UPDATE posts SET remote_container_id = ? WHERE id = ?", (value, post_id))

    def _status(self, video_id: str, token: str) -> dict[str, Any]:
        return graph_request(
            "GET",
            f"{GRAPH_BASE_URL}/{video_id}",
            token,
            error_label="Facebook reel status network error",
            params={"fields": "status"},
            timeout=30.0,
        )

    def _upload(self, video_id: str, token: str, video_path: Path) -> None:
        """Step 2: sends the master file itself (no public URL needed, so no R2 copy for Facebook)."""
        body = video_path.read_bytes()
        try:
            resp = httpx.post(
                f"{RUPLOAD_BASE}/{video_id}",
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(len(body)),
                    "Content-Type": "application/octet-stream",
                },
                content=body,
                timeout=UPLOAD_TIMEOUT_S,
            )
        except httpx.RequestError as exc:
            raise TransientPostError(f"Facebook reel upload network error: {exc}") from exc
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code >= 400:
            raise classify_meta_error(resp.status_code, data)
        if not data.get("success"):
            raise TransientPostError(f"Facebook reel upload not confirmed: {data}")

    def _finish(self, page_id: str, token: str, video_id: str, caption: str) -> None:
        """Step 3: publishes. A timeout here is retried by reading the status first."""
        graph_request(
            "POST",
            f"{GRAPH_BASE_URL}/{page_id}/video_reels",
            token,
            error_label="Facebook reel finish network error",
            data={
                "video_id": video_id,
                "upload_phase": "finish",
                "video_state": "PUBLISHED",
                "description": caption,
            },
            timeout=120.0,
        )

    def _permalink(self, video_id: str, token: str) -> str:
        fallback = f"https://www.facebook.com/reel/{video_id}"
        try:
            data = graph_request(
                "GET",
                f"{GRAPH_BASE_URL}/{video_id}",
                token,
                error_label="Facebook reel permalink network error",
                params={"fields": "permalink_url"},
                timeout=20.0,
            )
        except (TransientPostError, PermanentPostError):
            return fallback
        link = str(data.get("permalink_url") or "").strip()
        if link.startswith("/"):
            link = f"https://www.facebook.com{link}"
        return link or fallback

    def fetch_metrics(
        self, account: dict[str, Any], external_post_id: str
    ) -> dict[str, int | None]:
        token = self.secrets.get(str(account["secret_key"]))
        if not token or not external_post_id:
            raise MetricsFetchError(f"Facebook metrics: missing token or post id (account #{account.get('id')})")
        try:
            resp = httpx.get(
                f"{GRAPH_BASE_URL}/{external_post_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "views,likes.summary(true),comments.summary(true)"},
                timeout=20.0,
            )
            if resp.status_code != 200:
                metrics_http_outcome(resp.status_code, "Facebook metrics")
                return empty_metrics()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MetricsFetchError(f"Facebook metrics: {exc}") from exc
        views = data.get("views")
        likes = ((data.get("likes") or {}).get("summary") or {}).get("total_count")
        comments = ((data.get("comments") or {}).get("summary") or {}).get("total_count")
        return {
            "views": int(views) if views is not None else None,
            "likes": int(likes) if likes is not None else None,
            "comments": int(comments) if comments is not None else None,
            "shares": None,
        }
