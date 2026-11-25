"""Shared domain services used across API v1 and legacy routes without reverse dependencies."""
from __future__ import annotations

from videocreator.services.assets import (
    ALLOWED_AUDIO_EXTENSIONS,
    MAX_AUDIO_UPLOAD_BYTES,
    import_audio_asset,
    probe_audio_duration,
)
from videocreator.services.secret_keys import KNOWN_SECRET_KEYS
from videocreator.services.voices_catalog import AVAILABLE_VOICE_CATALOG

__all__ = [
    "ALLOWED_AUDIO_EXTENSIONS",
    "AVAILABLE_VOICE_CATALOG",
    "KNOWN_SECRET_KEYS",
    "MAX_AUDIO_UPLOAD_BYTES",
    "import_audio_asset",
    "probe_audio_duration",
]
