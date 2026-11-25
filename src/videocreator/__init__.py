"""Video Creator package."""
from __future__ import annotations

import ipaddress
import os

__version__ = "2.1.0"


def _normalize_no_proxy_for_httpx() -> None:
    """`httpx` 0.28 turns bracketed IPv6 entries like `[::1]` in `NO_PROXY` into `all://*[::1]`,
    raising `InvalidURL: Invalid port: ':1]'`. Unbracketing pure IPv6 literals to `::1` preserves
    the exact same `NO_PROXY` host list while letting `httpx` build `all://[::1]` cleanly."""
    for key in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(key)
        if not raw or "[" not in raw:
            continue
        cleaned: list[str] = []
        seen: set[str] = set()
        for part in raw.split(","):
            tok = part.strip()
            if tok.startswith("[") and tok.endswith("]"):
                inner = tok[1:-1]
                try:
                    ipaddress.IPv6Address(inner)
                    tok = inner
                except ValueError:
                    pass
            if tok and tok not in seen:
                seen.add(tok)
                cleaned.append(tok)
        os.environ[key] = ",".join(cleaned)


_normalize_no_proxy_for_httpx()
