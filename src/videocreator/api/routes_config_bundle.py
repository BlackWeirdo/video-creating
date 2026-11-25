"""Backward-compatible facade re-exporting `videocreator.api.mounts.config_bundle`."""
from __future__ import annotations

from videocreator.api.mounts.config_bundle import (
    MAX_IMPORT_VCX_BYTES,
    export_settings_route,
    import_settings_route,
    router,
)

__all__ = [
    "MAX_IMPORT_VCX_BYTES",
    "export_settings_route",
    "import_settings_route",
    "router",
]
