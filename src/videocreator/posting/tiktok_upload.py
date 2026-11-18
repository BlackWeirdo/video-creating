"""TikTok FILE_UPLOAD transfer: chunk planning, chunk upload, and API error classification."""
from __future__ import annotations

from typing import Any

import httpx

from videocreator.posting.base import PermanentPostError, TransientPostError

# Media transfer guide: a chunk is 5-64 MB, the last one may absorb the remainder (up to 128 MB);
# a file up to 64 MB can go as one chunk, a larger one must be split.
MAX_SINGLE_CHUNK_BYTES = 64 * 1024 * 1024
MULTI_CHUNK_BYTES = 32 * 1024 * 1024


def plan_chunks(video_size: int) -> tuple[int, int]:
    """Returns `(chunk_size, total_chunk_count)` for a FILE_UPLOAD of `video_size` bytes."""
    if video_size <= MAX_SINGLE_CHUNK_BYTES:
        return video_size, 1
    return MULTI_CHUNK_BYTES, video_size // MULTI_CHUNK_BYTES


def source_info(video_size: int) -> dict[str, Any]:
    chunk_size, total = plan_chunks(video_size)
    return {
        "source": "FILE_UPLOAD",
        "video_size": video_size,
        "chunk_size": chunk_size,
        "total_chunk_count": total,
    }


def upload_chunks(client: httpx.Client, upload_url: str, video_bytes: bytes) -> None:
    """PUTs the chunks in order; the last chunk carries the remainder."""
    video_size = len(video_bytes)
    chunk_size, total = plan_chunks(video_size)
    for idx in range(total):
        first = idx * chunk_size
        last = video_size - 1 if idx == total - 1 else first + chunk_size - 1
        try:
            resp = client.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(last - first + 1),
                    "Content-Range": f"bytes {first}-{last}/{video_size}",
                },
                content=video_bytes[first : last + 1],
            )
        except httpx.RequestError as exc:
            raise TransientPostError(f"TikTok upload chunk network error: {exc}") from exc
        if resp.status_code >= 500 or resp.status_code == 429:
            raise TransientPostError(f"TikTok upload chunk transient error ({resp.status_code})")
        if resp.status_code >= 400:
            raise PermanentPostError(f"TikTok upload chunk failed ({resp.status_code}): {resp.text[:200]}")


def check_tiktok_response(resp: httpx.Response) -> None:
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
