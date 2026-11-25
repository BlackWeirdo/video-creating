"""Muse Gateway integration package: hardened client, sidecar, pairing, multi-lane dispatcher & storyboard."""
from __future__ import annotations

from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import (
    MuseAuthError,
    MuseGatewayError,
    MuseInputError,
    MuseQuotaWait,
    MuseUnavailable,
    MuseUnsafeGatewayError,
)
from videocreator.muse_gateway.pairing import poll_gateway_pairing, start_gateway_pairing
from videocreator.muse_gateway.security import (
    assert_hardened_config_payload,
    assert_trusted_media_url,
    sanitize_prompt,
    strip_account_secrets,
    validate_gateway_base_url,
)
from videocreator.muse_gateway.sidecar import (
    ensure_muse_sidecar_running,
    get_sidecar_runtime_status,
    resolve_gateway_entry,
    stop_muse_sidecar,
)

__all__ = [
    "MuseAuthError",
    "MuseGatewayClient",
    "MuseGatewayError",
    "MuseInputError",
    "MuseQuotaWait",
    "MuseUnavailable",
    "MuseUnsafeGatewayError",
    "assert_hardened_config_payload",
    "assert_trusted_media_url",
    "ensure_muse_sidecar_running",
    "get_sidecar_runtime_status",
    "poll_gateway_pairing",
    "resolve_gateway_entry",
    "sanitize_prompt",
    "start_gateway_pairing",
    "stop_muse_sidecar",
    "strip_account_secrets",
    "validate_gateway_base_url",
]
