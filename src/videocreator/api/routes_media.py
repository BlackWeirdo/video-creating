"""Backward-compatible facade re-exporting `videocreator.api.mounts.media`."""
from __future__ import annotations

from videocreator.api.mounts.media import router, serve_media

__all__ = ["router", "serve_media"]
