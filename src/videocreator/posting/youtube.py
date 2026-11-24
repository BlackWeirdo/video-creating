"""YouTube Data API v3 Resumable Upload & Statistics Reader (Phase 03, V2-YT-01)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.probe import probe_video
from videocreator.posting.base import (
    MetricsFetchError,
    PermanentPostError,
    PostResult,
    TransientPostError,
    check_preflight_or_raise,
    empty_metrics,
)
from videocreator.secrets_store import SecretsStore

YOUTUBE_UPLOAD_INIT_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
)
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def _build_youtube_title(video_row: dict[str, Any], caption: str, *, is_short: bool) -> str:
    plan = loads_or(video_row.get("plan_json"), {})
    plan_title = str(plan.get("title") or "").strip() if isinstance(plan, dict) else ""
    first_line = next((ln.strip() for ln in caption.splitlines() if ln.strip()), "")
    base = plan_title or first_line or f"Video #{video_row.get('id', '')}".strip()
    if is_short and "#shorts" not in base.lower():
        if len(base) <= 91:
            base = f"{base} #Shorts"
        else:
            base = f"{base[:91].rstrip()} #Shorts"
    return base[:100]


class YouTubePoster:
    """Resumable upload poster + statistics reader for YouTube Data API v3."""

    platform = "youtube"

    def __init__(
        self,
        paths: AppPaths,
        secrets_store: SecretsStore | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.paths = paths
        self.secrets = secrets_store or SecretsStore(paths.secrets_file)
        self._http_client = http_client

    def publish(
        self,
        account: dict[str, Any],
        video_url: str,
        video_path: Path,
        caption: str,
        post: dict[str, Any],
    ) -> PostResult:
        del video_url  # YouTube receives raw binary via resumable PUT, not a staging URL.
        check_preflight_or_raise(self.paths.config_file, video_path, self.platform)

        secret_key = str(account.get("secret_key") or "")
        access_token = (self.secrets.get(secret_key) or "").strip() if secret_key else ""
        if not access_token:
            raise PermanentPostError(
                f"Thiếu access token YouTube cho tài khoản {account.get('name') or secret_key}"
            )

        info = probe_video(video_path)
        is_short = info.height > info.width and info.duration_s <= 60.5
        video_id = int(post.get("video_id") or 0)
        video_row = {"id": video_id, "plan_json": post.get("plan_json") or "{}"}
        if not video_row["plan_json"] or video_row["plan_json"] == "{}":
            from videocreator.db import query_one

            db_v = query_one(self.paths.db_file, "SELECT id, plan_json FROM videos WHERE id = ?", (video_id,))
            if db_v is not None:
                video_row = db_v

        title = _build_youtube_title(video_row, caption, is_short=is_short)
        desc = caption.strip()
        if is_short and "#shorts" not in desc.lower():
            desc = f"{desc}\n\n#Shorts".strip()

        video_bytes = video_path.read_bytes()
        metadata = {
            "snippet": {
                "title": title,
                "description": desc[:5000],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        own_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=120.0)
        try:
            init_resp = client.post(
                YOUTUBE_UPLOAD_INIT_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Length": str(len(video_bytes)),
                    "X-Upload-Content-Type": "video/mp4",
                },
                content=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            )
            if init_resp.status_code in (401, 403):
                raise PermanentPostError(
                    f"YouTube từ chối upload (HTTP {init_resp.status_code}): {init_resp.text[:300]}"
                )
            if init_resp.status_code == 429 or init_resp.status_code >= 500:
                raise TransientPostError(
                    f"YouTube tạm gián đoạn HTTP {init_resp.status_code}: {init_resp.text[:250]}"
                )
            if init_resp.status_code >= 400:
                raise PermanentPostError(
                    f"YouTube upload init lỗi HTTP {init_resp.status_code}: {init_resp.text[:300]}"
                )

            upload_url = init_resp.headers.get("Location") or init_resp.headers.get("location") or ""
            if not upload_url:
                raise TransientPostError("YouTube resumable upload không trả về header Location")

            put_resp = client.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(video_bytes)),
                },
                content=video_bytes,
            )
            if put_resp.status_code in (401, 403):
                raise PermanentPostError(
                    f"YouTube upload PUT bị từ chối HTTP {put_resp.status_code}: {put_resp.text[:300]}"
                )
            if put_resp.status_code == 429 or put_resp.status_code >= 500:
                raise TransientPostError(
                    f"YouTube upload PUT tạm lỗi HTTP {put_resp.status_code}: {put_resp.text[:250]}"
                )
            if put_resp.status_code >= 400:
                raise PermanentPostError(
                    f"YouTube upload PUT lỗi HTTP {put_resp.status_code}: {put_resp.text[:300]}"
                )

            data = put_resp.json() or {}
            yt_id = str(data.get("id") or "").strip()
            if not yt_id:
                raise TransientPostError(f"YouTube không trả về video id: {put_resp.text[:250]}")

            permalink = (
                f"https://www.youtube.com/shorts/{yt_id}"
                if is_short
                else f"https://www.youtube.com/watch?v={yt_id}"
            )
            return PostResult(status="posted", external_post_id=yt_id, permalink=permalink)
        except (PermanentPostError, TransientPostError):
            raise
        except httpx.HTTPError as exc:
            raise TransientPostError(f"Lỗi mạng YouTube upload: {exc}") from exc
        finally:
            if own_client:
                client.close()

    def fetch_metrics(
        self, account: dict[str, Any], external_post_id: str
    ) -> dict[str, int | None]:
        secret_key = str(account.get("secret_key") or "")
        access_token = (self.secrets.get(secret_key) or "").strip() if secret_key else ""
        if not access_token:
            raise MetricsFetchError("Thiếu access token YouTube để đọc statistics")

        own_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=30.0)
        try:
            resp = client.get(
                YOUTUBE_VIDEOS_URL,
                params={"part": "statistics", "id": external_post_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code in (401, 429) or resp.status_code >= 500:
                raise MetricsFetchError(f"YouTube statistics HTTP {resp.status_code}")
            if resp.status_code >= 400:
                return empty_metrics()
            items = (resp.json() or {}).get("items") or []
            if not items:
                return empty_metrics()
            stats = items[0].get("statistics") or {}
            return {
                "views": int(stats["viewCount"]) if "viewCount" in stats else None,
                "likes": int(stats["likeCount"]) if "likeCount" in stats else None,
                "comments": int(stats["commentCount"]) if "commentCount" in stats else None,
                "shares": None,
            }
        except MetricsFetchError:
            raise
        except httpx.HTTPError as exc:
            raise MetricsFetchError(f"YouTube metrics HTTP error: {exc}") from exc
        finally:
            if own_client:
                client.close()
