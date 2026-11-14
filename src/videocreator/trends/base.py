"""TrendSource protocol and TrendItem / WatchItem dataclasses (Phase 12)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class WatchItem:
    id: int
    source: str
    kind: str  # account | hashtag | keyword | page
    value: str
    enabled: bool = True


@dataclass
class TrendItem:
    source: str
    external_id: str
    url: str
    author: str
    caption: str
    published_at: datetime
    metrics: dict[str, Any] = field(default_factory=dict)
    video_url: str | None = None


class TrendSource(Protocol):
    name: str
    kinds: tuple[str, ...]

    def status(self) -> tuple[bool, str | None]:
        """Returns `(is_enabled, disabled_reason)`."""
        ...

    def fetch(self, watch: WatchItem) -> list[TrendItem]:
        """Fetches trend items for a single watch item."""
        ...
