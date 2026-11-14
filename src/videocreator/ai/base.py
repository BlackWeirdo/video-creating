"""Core AIProvider protocol and AI error hierarchy (Phase 04 & Phase 18)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
RouteKind = Literal["subscription", "api", "manual"]
AIRole = Literal["vision", "writer", "checker", "studio"]


class AIError(RuntimeError):
    """Base exception for AI provider and routing failures."""


class BudgetExceeded(AIError):
    """Raised when an API call would exceed the configured daily USD budget."""


class ProviderQuotaExhausted(AIError):
    """Raised when a subscription CLI or API provider hits a rate/quota limit."""

    def __init__(self, provider: str, message: str, retry_after_s: int = 3600) -> None:
        super().__init__(message)
        self.provider = provider
        self.retry_after_s = retry_after_s


class ProviderAuthError(AIError):
    """Raised when a CLI or API provider is not authenticated or has an invalid key."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(message)
        self.provider = provider


class SchemaValidationError(AIError):
    """Raised when a provider response fails Pydantic schema validation after retry."""


class AIProvider(Protocol):
    """Unified interface for both subscription CLI and paid API providers."""

    name: str
    route_kind: RouteKind

    def describe_video(
        self,
        video: Path,
        prompt: str,
        schema: type[T],
        *,
        thumbnails: list[Path] | None = None,
    ) -> T:
        ...

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        ...
