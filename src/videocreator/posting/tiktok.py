"""TikTok Content Posting API v2 adapter supporting `inbox` (draft) and `direct` modes (Phase 11)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from videocreator.paths import AppPaths
from videocreator.posting.base import (
    PermanentPostError,
    PostResult,
    TransientPostError,
    check_preflight_or_raise,
    empty_metrics,
)
from videocreator.posting.tiktok_upload import check_tiktok_response, source_info, upload_chunks
from videocreator.secrets_store import SecretsStore

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"
MAX_POLLS = 18
POLL_SLEEP_S = 5.0

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
        settings = check_preflight_or_raise(self.paths.config_file, video_path, "tiktok")
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
                "source_info": source_info(video_size)
            },
        )
        check_tiktok_response(resp)
        data = (resp.json() or {}).get("data") or {}
        publish_id = str(data.get("publish_id") or "")
        upload_url = str(data.get("upload_url") or "")
        if not publish_id or not upload_url:
            raise PermanentPostError(f"TikTok inbox init missing publish_id/upload_url: {data}")

        upload_chunks(client, upload_url, video_bytes)
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
        check_tiktok_response(r_info)
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
                "source_info": source_info(video_size),
            },
        )
        check_tiktok_response(r_init)
        init_data = (r_init.json() or {}).get("data") or {}
        publish_id = str(init_data.get("publish_id") or "")
        upload_url = str(init_data.get("upload_url") or "")
        if not publish_id or not upload_url:
            raise PermanentPostError(f"TikTok direct init missing publish_id/upload_url: {init_data}")

        upload_chunks(client, upload_url, video_bytes)

        for _ in range(MAX_POLLS):
            r_st = client.post(
                f"{TIKTOK_API_BASE}/post/publish/status/fetch/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={"publish_id": publish_id},
            )
            check_tiktok_response(r_st)
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

    def fetch_metrics(
        self, account: dict[str, Any], external_post_id: str
    ) -> dict[str, int | None]:
        return empty_metrics()
