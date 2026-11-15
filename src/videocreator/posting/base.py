"""Poster protocol, PostResult, and Transient/Permanent error hierarchy (Phase 07)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from videocreator.config import Settings, load_settings
from videocreator.pipeline.preflight import check_platform


@dataclass(frozen=True)
class PostResult:
    status: str  # "posted" | "needs_user_action"
    external_post_id: str | None = None
    permalink: str | None = None


class TransientPostError(RuntimeError):
    """Temporary network, 5xx, or rate-limit failure eligible for exponential backoff retry."""


class PendingPostError(TransientPostError):
    """The platform has accepted the post and is still processing it. Waiting is expected, so it
    is retried on a slower schedule with a bigger allowance than a real failure, and running out
    ends in "check and confirm" (`needs_user_action`), never in "failed" (it may well be live)."""


class PermanentPostError(RuntimeError):
    """Unrecoverable auth (code 190), permission, preflight, or media rejection failure."""


class MetricsFetchError(RuntimeError):
    """Metrics could not be read this time (network, HTTP error, missing token). Nothing is recorded,
    so the checkpoint is tried again on the next run; a platform that simply has no data returns
    `empty_metrics()` instead."""


class Poster(Protocol):
    platform: str

    def publish(
        self,
        account: dict[str, Any],
        video_url: str,
        video_path: Path,
        caption: str,
        post: dict[str, Any],
    ) -> PostResult:
        ...


Account = dict[str, Any]


class MetricsReader(Protocol):
    def fetch_metrics(
        self, account: dict[str, Any], external_post_id: str
    ) -> dict[str, int | None]:
        ...


def empty_metrics() -> dict[str, int | None]:
    """Metrics of a post that could not be read."""
    return {"views": None, "likes": None, "comments": None, "shares": None}


def metrics_http_outcome(status_code: int, label: str) -> None:
    """Decides what a non-200 metrics reply means: network-like failures (429, 5xx) raise
    `MetricsFetchError` so the checkpoint is tried again; any other 4xx (post deleted, no
    permission, an id that is not a post) is final, and the caller records "no data"."""
    if status_code == 429 or status_code >= 500:
        raise MetricsFetchError(f"{label} HTTP {status_code}")


def check_preflight_or_raise(config_file: Path, video_path: Path, platform: str) -> Settings:
    """Raises `PermanentPostError` when the video breaks the platform's format limits; returns the settings."""
    settings = load_settings(config_file)
    limit = settings.platform_limits.get(platform)
    if limit is not None:
        errors = check_platform(video_path, platform, limit)
        if errors:
            raise PermanentPostError("; ".join(errors))
    return settings


def insight_values(items: list[dict[str, Any]]) -> dict[str, int]:
    """`{metric_name: value}` from a Graph API insights `data` list (first integer value of each metric)."""
    by_name: dict[str, int] = {}
    for item in items:
        values = item.get("values") or []
        if values and isinstance(values[0].get("value"), int):
            by_name[str(item.get("name") or "")] = int(values[0]["value"])
    return by_name

