"""Network retry and error classification shared by the paid API providers."""
from __future__ import annotations

import re
import time
from typing import Callable, TypeVar

from videocreator.ai.base import AIError, ProviderAuthError, ProviderQuotaExhausted

R = TypeVar("R")

MAX_NETWORK_ATTEMPTS = 3
QUOTA_REST_S = 1800


def _matches_any(exc: Exception, lower_msg: str, markers: tuple[str, ...]) -> bool:
    status_attr = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    status_str = str(status_attr) if isinstance(status_attr, int) else ""
    for marker in markers:
        m = marker.lower()
        if m.isdigit():
            if status_str == m or re.search(rf"(?<![0-9]){re.escape(m)}(?![0-9])", lower_msg):
                return True
        elif m in lower_msg:
            return True
    return False


def call_api_with_retry(
    send: Callable[[], R],
    *,
    provider: str,
    label: str,
    auth_markers: tuple[str, ...],
    quota_markers: tuple[str, ...],
    quota_label: str,
    server_codes: tuple[str, ...],
) -> R:
    """Calls `send`, retrying rate limits and server errors with 1 s then 2 s of backoff.

    Auth failures raise `ProviderAuthError`; a rate limit that survives the retries raises
    `ProviderQuotaExhausted`; anything else raises `AIError`."""
    for attempt in range(MAX_NETWORK_ATTEMPTS):
        try:
            return send()
        except Exception as exc:
            msg = str(exc)
            lower = msg.lower()
            can_retry = attempt < MAX_NETWORK_ATTEMPTS - 1
            if _matches_any(exc, lower, auth_markers):
                raise ProviderAuthError(provider, f"{label} auth error: {msg}") from exc
            if _matches_any(exc, lower, quota_markers):
                if can_retry:
                    time.sleep(2 ** attempt)
                    continue
                raise ProviderQuotaExhausted(
                    provider, f"{label} {quota_label}: {msg}", retry_after_s=QUOTA_REST_S
                ) from exc
            if can_retry and _matches_any(exc, lower, server_codes):
                time.sleep(2 ** attempt)
                continue
            raise AIError(f"{label} call failed: {msg}") from exc
    raise AIError(f"{label} returned no response")
