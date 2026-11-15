"""Insights of a published Threads post."""
from __future__ import annotations

import httpx

from videocreator.posting.base import empty_metrics, insight_values

THREADS_API_BASE = "https://graph.threads.net/v1.0"


def fetch_threads_metrics(token: str, external_post_id: str) -> dict[str, int | None]:
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
                return empty_metrics()
            by_name = insight_values(resp.json().get("data") or [])
            return {
                "views": by_name.get("views"),
                "likes": by_name.get("likes"),
                "comments": by_name.get("replies"),
                "shares": by_name.get("reposts"),
            }
    except Exception:
        return empty_metrics()
