"""Network retry and error classification shared by the paid API providers."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from videocreator.ai.base import AIError, ProviderAuthError, ProviderQuotaExhausted

R = TypeVar("R")

MAX_NETWORK_ATTEMPTS = 3
QUOTA_REST_S = 1800


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
            if any(marker in lower for marker in auth_markers):
                raise ProviderAuthError(provider, f"{label} auth error: {msg}") from exc
            if any(marker in lower for marker in quota_markers):
                if can_retry:
                    time.sleep(2 ** attempt)
                    continue
                raise ProviderQuotaExhausted(
                    provider, f"{label} {quota_label}: {msg}", retry_after_s=QUOTA_REST_S
                ) from exc
            if can_retry and any(code in lower for code in server_codes):
                time.sleep(2 ** attempt)
                continue
            raise AIError(f"{label} call failed: {msg}") from exc
    raise AIError(f"{label} returned no response")
