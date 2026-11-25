"""Backward-compatible facade re-exporting `videocreator.api.mounts.freecut_bridge`."""
from __future__ import annotations

from videocreator.api.mounts.freecut_bridge import (
    HeartbeatBody,
    api_editor_get_job,
    api_editor_heartbeat,
    api_editor_prepare_job,
    api_editor_put_result,
    router,
    serve_freecut_editor,
    serve_freecut_moss_tts,
    serve_freecut_root_assets,
)

__all__ = [
    "HeartbeatBody",
    "api_editor_get_job",
    "api_editor_heartbeat",
    "api_editor_prepare_job",
    "api_editor_put_result",
    "router",
    "serve_freecut_editor",
    "serve_freecut_moss_tts",
    "serve_freecut_root_assets",
]
