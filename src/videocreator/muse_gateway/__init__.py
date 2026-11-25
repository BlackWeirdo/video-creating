"""Muse Gateway integration package: hardened client, sidecar, pairing, multi-lane dispatcher & storyboard."""
from __future__ import annotations

from videocreator.muse_gateway.capacity import (
    compute_gateway_capacity,
    is_daily_account_cap_reached,
)
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.dispatcher import (
    register_muse_downstream_hook,
    run_muse_dispatcher_tick,
)
from videocreator.muse_gateway.errors import (
    MuseAuthError,
    MuseGatewayError,
    MuseInputError,
    MuseQuotaWait,
    MuseUnavailable,
    MuseUnsafeGatewayError,
)
from videocreator.muse_gateway.pairing import poll_gateway_pairing, start_gateway_pairing
from videocreator.muse_gateway.refs import (
    stage_uploaded_muse_ref,
    validate_muse_refs_policy,
)
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
from videocreator.muse_gateway.store import (
    count_active_muse_tasks,
    create_muse_task,
    get_muse_task,
    list_muse_tasks,
    update_muse_task,
)
from videocreator.muse_gateway.webhook import (
    process_muse_webhook_event,
    verify_muse_webhook_signature,
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
    "compute_gateway_capacity",
    "count_active_muse_tasks",
    "create_muse_task",
    "ensure_muse_sidecar_running",
    "get_muse_task",
    "get_sidecar_runtime_status",
    "is_daily_account_cap_reached",
    "list_muse_tasks",
    "poll_gateway_pairing",
    "process_muse_webhook_event",
    "register_muse_downstream_hook",
    "resolve_gateway_entry",
    "run_muse_dispatcher_tick",
    "sanitize_prompt",
    "stage_uploaded_muse_ref",
    "start_gateway_pairing",
    "stop_muse_sidecar",
    "strip_account_secrets",
    "update_muse_task",
    "validate_gateway_base_url",
    "validate_muse_refs_policy",
    "verify_muse_webhook_signature",
]
