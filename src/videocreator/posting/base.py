"""Poster protocol, PostResult, and Transient/Permanent error hierarchy (Phase 07)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class PostResult:
    status: str  # "posted" | "needs_user_action"
    external_post_id: str | None = None
    permalink: str | None = None


class TransientPostError(RuntimeError):
    """Temporary network, 5xx, or rate-limit failure eligible for exponential backoff retry."""


class PermanentPostError(RuntimeError):
    """Unrecoverable auth (code 190), permission, preflight, or media rejection failure."""


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

