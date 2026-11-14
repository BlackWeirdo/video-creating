"""Threads video container + publish adapter with crash-safe container resume (`FR-PST-07`, Phase 11)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from videocreator.config import load_settings
from videocreator.db import get_conn
from videocreator.paths import AppPaths
from videocreator.pipeline.preflight import check_platform
from videocreator.posting.base import (
    PermanentPostError,
    PostResult,
    TransientPostError,
)
from videocreator.posting.meta_auth import classify_meta_error
from videocreator.secrets_store import SecretsStore

THREADS_API_BASE = "https://graph.threads.net/v1.0"
MAX_POLLS = 24
POLL_SLEEP_S = 5.0


class ThreadsPoster:
    platform = "threads"

    def __init__(self, paths: AppPaths, secrets_store: SecretsStore) -> None:
        self.paths = paths
        self.secrets = secrets_store

    def publish(
        self,
        account: dict[str, Any],
        video_url: str | None,
        video_path: Path,
        caption: str,
        post: dict[str, Any],
    ) -> PostResult:
        settings = load_settings(self.paths.config_file)
        limit = settings.platform_limits.get("threads")
        if limit is not None:
            pf_errs = check_platform(video_path, "threads", limit)
            if pf_errs:
                raise PermanentPostError("; ".join(pf_errs))
        if not video_url:
            raise PermanentPostError("Threads requires a public R2 video_url")

        token = self.secrets.get(str(account["secret_key"]))
        if not token:
            raise PermanentPostError(
                f"Missing access token for Threads account #{account['id']}"
            )

        user_id = str(account["external_id"])
        post_id = int(post["id"])
        container_id = str(post.get("remote_container_id") or "").strip()

        with httpx.Client(timeout=45.0) as client:
            if container_id:
                status = self._poll_container_status(client, container_id, token)
                if status in ("ERROR", "EXPIRED"):
                    container_id = ""

            if not container_id:
                container_id = self._create_container(
                    client,
                    user_id=user_id,
                    token=token,
                    video_url=video_url,
                    caption=caption[:500],
                )
                with get_conn(self.paths.db_file) as conn:
                    conn.execute(
                        "UPDATE posts SET remote_container_id = ? WHERE id = ?",
                        (container_id, post_id),
                    )

            for _ in range(MAX_POLLS):
                st = self._poll_container_status(client, container_id, token)
                if st in ("FINISHED", "PUBLISHED"):
                    break
                if st in ("ERROR", "EXPIRED"):
                    raise PermanentPostError(
                        f"Threads container {container_id} failed with status={st}"
                    )
                time.sleep(POLL_SLEEP_S)
            else:
                raise TransientPostError(
                    f"Threads container {container_id} still IN_PROGRESS after {MAX_POLLS} polls"
                )

            media_id = self._publish_container(
                client, user_id=user_id, token=token, container_id=container_id
            )
            permalink = self._fetch_permalink(client, media_id=media_id, token=token)
            return PostResult(
                status="posted",
                external_post_id=media_id,
                permalink=permalink or f"https://www.threads.net/t/{media_id}",
            )

    def _create_container(
        self,
        client: httpx.Client,
        *,
        user_id: str,
        token: str,
        video_url: str,
        caption: str,
    ) -> str:
        resp = client.post(
            f"{THREADS_API_BASE}/{user_id}/threads",
            data={
                "media_type": "VIDEO",
                "video_url": video_url,
                "text": caption,
                "access_token": token,
            },
        )
        if resp.status_code >= 400:
            self._raise_threads_error(resp)
        data = resp.json()
        cid = str(data.get("id") or "")
        if not cid:
            raise PermanentPostError(f"Threads container creation returned no id: {data}")
        return cid

    def _poll_container_status(
        self, client: httpx.Client, container_id: str, token: str
    ) -> str:
        resp = client.get(
            f"{THREADS_API_BASE}/{container_id}",
            params={"fields": "status,error_message", "access_token": token},
        )
        if resp.status_code >= 400:
            self._raise_threads_error(resp)
        data = resp.json()
        return str(data.get("status") or "IN_PROGRESS").upper()

    def _publish_container(
        self,
        client: httpx.Client,
        *,
        user_id: str,
        token: str,
        container_id: str,
    ) -> str:
        resp = client.post(
            f"{THREADS_API_BASE}/{user_id}/threads_publish",
            data={"creation_id": container_id, "access_token": token},
        )
        if resp.status_code >= 400:
            self._raise_threads_error(resp)
        data = resp.json()
        mid = str(data.get("id") or "")
        if not mid:
            raise PermanentPostError(f"Threads publish returned no id: {data}")
        return mid

    def _fetch_permalink(
        self, client: httpx.Client, *, media_id: str, token: str
    ) -> str | None:
        try:
            resp = client.get(
                f"{THREADS_API_BASE}/{media_id}",
                params={"fields": "id,permalink", "access_token": token},
            )
            if resp.status_code == 200:
                return resp.json().get("permalink")
        except Exception:
            pass
        return None

    def _raise_threads_error(self, resp: httpx.Response) -> None:
        try:
            data = resp.json() or {}
        except Exception:
            data = {}
        raise classify_meta_error(resp.status_code, data)

    def fetch_metrics(
        self, account: dict[str, Any], external_post_id: str
    ) -> dict[str, int | None]:
        token = self.secrets.get(str(account["secret_key"]))
        if not token or not external_post_id:
            return {"views": None, "likes": None, "comments": None, "shares": None}
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(
                    f"{THREADS_API_BASE}/{external_post_id}/insights",
                    params={
                        "metric": "views,likes,replies,reposts",
                        "access_token": token,
                    },
                )
                if resp.status_code != 200:
                    return {"views": None, "likes": None, "comments": None, "shares": None}
                items = resp.json().get("data") or []
                by_name: dict[str, int | None] = {}
                for it in items:
                    name = str(it.get("name") or "")
                    vals = it.get("values") or []
                    if vals and isinstance(vals[0].get("value"), int):
                        by_name[name] = int(vals[0]["value"])
                return {
                    "views": by_name.get("views"),
                    "likes": by_name.get("likes"),
                    "comments": by_name.get("replies"),
                    "shares": by_name.get("reposts"),
                }
        except Exception:
            return {"views": None, "likes": None, "comments": None, "shares": None}
