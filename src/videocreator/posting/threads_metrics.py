"""Insights of a published Threads post."""
from __future__ import annotations

import httpx

from videocreator.posting.base import MetricsFetchError, empty_metrics, insight_values, metrics_http_outcome

THREADS_API_BASE = "https://graph.threads.net/v1.0"


def fetch_threads_metrics(token: str, external_post_id: str) -> dict[str, int | None]:
    """Insights of one post; raises `MetricsFetchError` when they cannot be read this time."""
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
            try:
                err_body = resp.json()
            except Exception:
                err_body = None
            metrics_http_outcome(resp.status_code, "Threads metrics", err_body)
            return empty_metrics()
        by_name = insight_values(resp.json().get("data") or [])
    except (httpx.HTTPError, ValueError) as exc:
        raise MetricsFetchError(f"Threads metrics: {exc}") from exc
    return {
        "views": by_name.get("views"),
        "likes": by_name.get("likes"),
        "comments": by_name.get("replies"),
        "shares": by_name.get("reposts"),
    }
