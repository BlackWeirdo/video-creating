"""Finding a post that was already published from a container whose publish reply was lost.

Instagram and Threads publish in two steps. If the app stops (or times out) after Meta published
the container but before the reply arrived, a retry must not publish again: it looks for the
post among the account's latest posts instead (`FR-PST-07`, `NFR-REL-01`).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx

from videocreator.posting.base import PostResult
from videocreator.posting.instagram_graph import graph_request
from videocreator.posting.meta_auth import GRAPH_BASE_URL
from videocreator.posting.threads_metrics import THREADS_API_BASE
from videocreator.timeutil import parse_iso_utc

SEARCH_LIMIT = 10
SLACK = timedelta(hours=1)  # the container may be created a little before the scheduled time


def find_recent_post(items: list[dict[str, Any]], caption: str, not_before_iso: str | None) -> dict[str, Any] | None:
    """The newest item whose text equals `caption` and that is not older than `not_before_iso` (pure)."""
    want = (caption or "").strip()
    floor = parse_iso_utc(not_before_iso)
    for item in items:
        text = str(item.get("caption") or item.get("text") or "").strip()
        when = parse_iso_utc(str(item.get("timestamp") or ""))
        if text != want:
            continue
        if floor is not None and when is not None and when < floor - SLACK:
            continue
        return item
    return None


def unconfirmed_result(container_id: str) -> PostResult:
    """Published by Meta but not found: a person checks and confirms with 'Đã đăng'."""
    return PostResult(status="needs_user_action", external_post_id=container_id, permalink=None)


def instagram_recent_media(ig_id: str, token: str) -> list[dict[str, Any]]:
    data = graph_request(
        "GET",
        f"{GRAPH_BASE_URL}/{ig_id}/media",
        token,
        error_label="Instagram media list network error",
        params={"fields": "id,caption,timestamp,permalink", "limit": str(SEARCH_LIMIT)},
        timeout=30.0,
    )
    return list(data.get("data") or [])


def threads_recent_posts(client: httpx.Client, user_id: str, token: str) -> list[dict[str, Any]]:
    resp = client.get(
        f"{THREADS_API_BASE}/{user_id}/threads",
        params={"fields": "id,text,timestamp,permalink", "limit": str(SEARCH_LIMIT), "access_token": token},
    )
    if resp.status_code >= 400:
        return []
    return list((resp.json() or {}).get("data") or [])
