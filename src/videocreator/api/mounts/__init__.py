"""Essential non-UI mounts shared by V2 Next.js Studio UI (`/files`, `/freecut`, `/oauth`, `/ui-unavailable`)."""
from __future__ import annotations

from videocreator.api.mounts.config_bundle import (
    MAX_IMPORT_VCX_BYTES,
    router as config_bundle_router,
)
from videocreator.api.mounts.freecut_bridge import (
    HeartbeatBody,
    router as freecut_router,
)
from videocreator.api.mounts.media import router as media_router
from videocreator.api.mounts.oauth import router as oauth_router
from videocreator.api.mounts.ui_fallback import router as ui_fallback_router

__all__ = [
    "HeartbeatBody",
    "MAX_IMPORT_VCX_BYTES",
    "config_bundle_router",
    "freecut_router",
    "media_router",
    "oauth_router",
    "ui_fallback_router",
]
