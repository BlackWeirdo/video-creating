"""Backward-compatible facade re-exporting `videocreator.api.mounts.oauth`."""
from __future__ import annotations

from videocreator.api.mounts.oauth import (
    oauth_callback_route,
    oauth_paste_code_route,
    oauth_start_route,
    router,
)

__all__ = [
    "oauth_callback_route",
    "oauth_paste_code_route",
    "oauth_start_route",
    "router",
]
