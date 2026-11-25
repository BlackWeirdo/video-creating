"""Typed exceptions for Muse Gateway integration."""
from __future__ import annotations


class MuseGatewayError(RuntimeError):
    """Base error raised by Muse Gateway client, sidecar, or dispatcher."""


class MuseAuthError(MuseGatewayError):
    """Raised on HTTP 401/403 from Muse Gateway (`/v1/*` API key invalid or model disallowed)."""


class MuseUnavailable(MuseGatewayError):
    """Raised when Muse Gateway cannot be reached or returns a transient 5xx error."""


class MuseUnsafeGatewayError(MuseGatewayError):
    """Raised when the connected Muse Gateway does not pass `vc-hardened` (`cmdMode == 'off'`) checks."""


class MuseInputError(MuseGatewayError):
    """Raised on HTTP 400 invalid task/media request from Muse Gateway."""


class MuseQuotaWait(MuseGatewayError):
    """Raised when all Muse accounts are in cooldown or daily safety cap is reached."""

    def __init__(self, message: str, *, retry_after_s: int = 1800) -> None:
        super().__init__(message)
        self.retry_after_s = max(60, int(retry_after_s))


__all__ = [
    "MuseAuthError",
    "MuseGatewayError",
    "MuseInputError",
    "MuseQuotaWait",
    "MuseUnavailable",
    "MuseUnsafeGatewayError",
]
