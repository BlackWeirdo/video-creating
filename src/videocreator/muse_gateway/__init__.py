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
from videocreator.muse_gateway.storyboard import (
    STORYBOARD_ASSEMBLE_JOB_KIND,
    assemble_storyboard,
    create_storyboard,
    delete_storyboard,
    get_storyboard,
    list_storyboards,
    regenerate_storyboard_segment,
    run_storyboard_assemble_job,
    start_storyboard_generation,
    update_storyboard,
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
    "STORYBOARD_ASSEMBLE_JOB_KIND",
    "assemble_storyboard",
    "assert_hardened_config_payload",
    "assert_trusted_media_url",
    "compute_gateway_capacity",
    "count_active_muse_tasks",
    "create_muse_task",
    "create_storyboard",
    "delete_storyboard",
    "ensure_muse_sidecar_running",
    "get_muse_task",
    "get_sidecar_runtime_status",
    "get_storyboard",
    "is_daily_account_cap_reached",
    "list_muse_tasks",
    "list_storyboards",
    "poll_gateway_pairing",
    "process_muse_webhook_event",
    "regenerate_storyboard_segment",
    "register_muse_downstream_hook",
    "resolve_gateway_entry",
    "run_muse_dispatcher_tick",
    "run_storyboard_assemble_job",
    "sanitize_prompt",
    "stage_uploaded_muse_ref",
    "start_gateway_pairing",
    "start_storyboard_generation",
    "stop_muse_sidecar",
    "strip_account_secrets",
    "update_muse_task",
    "update_storyboard",
    "validate_gateway_base_url",
    "validate_muse_refs_policy",
    "verify_muse_webhook_signature",
]
