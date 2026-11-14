"""TikTok Content Posting API v2 adapter supporting `inbox` (draft) and `direct` modes (Phase 11)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.pipeline.preflight import check_platform
from videocreator.posting.base import (
    PermanentPostError,
    PostResult,
    TransientPostError,
)
from videocreator.secrets_store import SecretsStore

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"
MAX_POLLS = 18
POLL_SLEEP_S = 5.0
# Media transfer guide: a chunk is 5-64 MB, the last one may absorb the remainder (up to 128 MB);
# a file up to 64 MB can go as one chunk, a larger one must be split.
MAX_SINGLE_CHUNK_BYTES = 64 * 1024 * 1024
MULTI_CHUNK_BYTES = 32 * 1024 * 1024


def plan_chunks(video_size: int) -> tuple[int, int]:
    """Returns `(chunk_size, total_chunk_count)` for a FILE_UPLOAD of `video_size` bytes."""
    if video_size <= MAX_SINGLE_CHUNK_BYTES:
        return video_size, 1
    return MULTI_CHUNK_BYTES, video_size // MULTI_CHUNK_BYTES


class TikTokPoster:
    platform = "tiktok"

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
        limit = settings.platform_limits.get("tiktok")
        if limit is not None:
            pf_errs = check_platform(video_path, "tiktok", limit)
            if pf_errs:
                raise PermanentPostError("; ".join(pf_errs))
        if not video_path.exists():
            raise PermanentPostError(f"TikTok video file not found: {video_path}")

        token = self.secrets.get(str(account["secret_key"]))
        if not token:
            raise PermanentPostError(
                f"Missing access token for TikTok account #{account['id']}"
            )

        mode = settings.tiktok.mode
        video_bytes = video_path.read_bytes()
        video_size = len(video_bytes)

        with httpx.Client(timeout=120.0) as client:
            if mode == "inbox":
                return self._publish_inbox(
                    client, token=token, video_bytes=video_bytes, video_size=video_size
                )
            return self._publish_direct(
                client,
                token=token,
                video_bytes=video_bytes,
                video_size=video_size,
                caption=caption[:2200],
                account_name=str(account.get("name") or "user"),
            )

    def _publish_inbox(
        self,
        client: httpx.Client,
        *,
        token: str,
        video_bytes: bytes,
        video_size: int,
    ) -> PostResult:
        resp = client.post(
            f"{TIKTOK_API_BASE}/post/publish/inbox/video/init/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={
                "source_info": self._source_info(video_size)
            },
        )
        self._check_tiktok_response(resp)
        data = (resp.json() or {}).get("data") or {}
        publish_id = str(data.get("publish_id") or "")
        upload_url = str(data.get("upload_url") or "")
        if not publish_id or not upload_url:
            raise PermanentPostError(f"TikTok inbox init missing publish_id/upload_url: {data}")

        self._upload_chunks(client, upload_url, video_bytes)
        return PostResult(
            status="needs_user_action",
            external_post_id=publish_id,
            permalink=None,
        )

    def _publish_direct(
        self,
        client: httpx.Client,
        *,
        token: str,
        video_bytes: bytes,
        video_size: int,
        caption: str,
        account_name: str,
    ) -> PostResult:
        # Query creator_info first per TikTok Direct Post guidelines
        r_info = client.post(
            f"{TIKTOK_API_BASE}/post/publish/creator_info/query/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={},
        )
        self._check_tiktok_response(r_info)
        info_data = (r_info.json() or {}).get("data") or {}
        privacy_options = info_data.get("privacy_level_options") or ["SELF_ONLY"]
        privacy_level = (
            "PUBLIC_TO_EVERYONE"
            if "PUBLIC_TO_EVERYONE" in privacy_options
            else privacy_options[0]
        )

        r_init = client.post(
            f"{TIKTOK_API_BASE}/post/publish/video/init/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={
                "post_info": {
                    "title": caption,
                    "privacy_level": privacy_level,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": self._source_info(video_size),
            },
        )
        self._check_tiktok_response(r_init)
        init_data = (r_init.json() or {}).get("data") or {}
        publish_id = str(init_data.get("publish_id") or "")
        upload_url = str(init_data.get("upload_url") or "")
        if not publish_id or not upload_url:
            raise PermanentPostError(f"TikTok direct init missing publish_id/upload_url: {init_data}")

        self._upload_chunks(client, upload_url, video_bytes)

        for _ in range(MAX_POLLS):
            r_st = client.post(
                f"{TIKTOK_API_BASE}/post/publish/status/fetch/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={"publish_id": publish_id},
            )
            self._check_tiktok_response(r_st)
            st_data = (r_st.json() or {}).get("data") or {}
            status = str(st_data.get("status") or "").upper()
            if status == "PUBLISH_COMPLETE":
                pub_id = str(
                    (st_data.get("publicaly_available_post_id") or [publish_id])[0]
                )
                return PostResult(
                    status="posted",
                    external_post_id=pub_id,
                    permalink=f"https://www.tiktok.com/@{account_name}/video/{pub_id}",
                )
            if status == "FAILED":
                fail_reason = st_data.get("fail_reason") or "TikTok publish failed"
                raise PermanentPostError(f"TikTok direct publish failed: {fail_reason}")
            time.sleep(POLL_SLEEP_S)

        raise TransientPostError(f"TikTok publish {publish_id} still processing after {MAX_POLLS} polls")

    @staticmethod
    def _source_info(video_size: int) -> dict[str, Any]:
        chunk_size, total = plan_chunks(video_size)
        return {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total,
        }

    def _upload_chunks(self, client: httpx.Client, upload_url: str, video_bytes: bytes) -> None:
        """PUTs the chunks in order; the last chunk carries the remainder."""
        video_size = len(video_bytes)
        chunk_size, total = plan_chunks(video_size)
        for idx in range(total):
            first = idx * chunk_size
            last = video_size - 1 if idx == total - 1 else first + chunk_size - 1
            resp = client.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(last - first + 1),
                    "Content-Range": f"bytes {first}-{last}/{video_size}",
                },
                content=video_bytes[first : last + 1],
            )
            if resp.status_code >= 500 or resp.status_code == 429:
                raise TransientPostError(f"TikTok upload chunk transient error ({resp.status_code})")
            if resp.status_code >= 400:
                raise PermanentPostError(f"TikTok upload chunk failed ({resp.status_code}): {resp.text[:200]}")

    def _check_tiktok_response(self, resp: httpx.Response) -> None:
        if resp.status_code >= 500 or resp.status_code == 429:
            raise TransientPostError(f"TikTok API transient HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise PermanentPostError(
                f"TikTok API error HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            err = (resp.json() or {}).get("error") or {}
        except Exception:
            err = {}
        code = str(err.get("code") or "ok")
        if code and code != "ok":
            msg = str(err.get("message") or code)
            if "rate_limit" in code.lower() or "internal" in code.lower():
                raise TransientPostError(f"TikTok API transient error ({code}): {msg}")
            raise PermanentPostError(f"TikTok API error ({code}): {msg}")

    def fetch_metrics(
        self, account: dict[str, Any], external_post_id: str
    ) -> dict[str, int | None]:
        return {"views": None, "likes": None, "comments": None, "shares": None}
