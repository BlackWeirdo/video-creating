"""Graph API calls of the Instagram Reels adapter: classified requests, permalink, insights."""
from __future__ import annotations
from typing import Any

import httpx

from videocreator.posting.base import MetricsFetchError, TransientPostError, insight_values
from videocreator.posting.meta_auth import GRAPH_BASE_URL, classify_meta_error

def graph_request(
    method: str, url: str, token: str, *, error_label: str, timeout: float, **kwargs: Any
) -> dict[str, Any]:
    """One Graph API call: network failures are transient, HTTP errors are classified by Meta's code."""
    try:
        resp = httpx.request(method, url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout, **kwargs)
    except httpx.RequestError as exc:
        raise TransientPostError(f"{error_label}: {exc}") from exc
    try:
        data = resp.json()
    except Exception:
        data = {}
    if resp.status_code >= 400:
        raise classify_meta_error(resp.status_code, data)
    return data


def fetch_reel_permalink(media_id: str, token: str) -> str:
    fallback = f"https://www.instagram.com/reel/{media_id}/"
    try:
        link_resp = httpx.get(
            f"{GRAPH_BASE_URL}/{media_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "permalink"},
            timeout=20.0,
        )
        if link_resp.status_code != 200:
            return fallback
        return str(link_resp.json().get("permalink") or fallback)
    except Exception:
        return fallback


def fetch_reel_insights(media_id: str, token: str) -> dict[str, int]:
    """`views` and `shares` of a reel; empty when Meta refuses them (e.g. no insights permission).

    Network and server errors raise `MetricsFetchError`, so the checkpoint is tried again later."""
    try:
        resp = httpx.get(
            f"{GRAPH_BASE_URL}/{media_id}/insights",
            headers={"Authorization": f"Bearer {token}"},
            params={"metric": "views,shares"},  # `plays` was replaced by `views`
            timeout=20.0,
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise MetricsFetchError(f"Instagram insights HTTP {resp.status_code}")
        if resp.status_code != 200:
            return {}
        return insight_values(resp.json().get("data") or [])
    except (httpx.HTTPError, ValueError) as exc:
        raise MetricsFetchError(f"Instagram insights: {exc}") from exc
