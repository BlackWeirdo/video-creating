"""HMAC-SHA256 verification and idempotent handler for Muse Gateway webhooks."""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

from videocreator.config import load_settings
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.dispatcher import (
    handle_remote_task_failure,
    run_downstream_hooks_for_task,
)
from videocreator.muse_gateway.media_import import import_completed_muse_task
from videocreator.muse_gateway.store import get_muse_task_by_gateway_id, update_muse_task
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore


def verify_muse_webhook_signature(
    raw_body: bytes, signature_header: str | None, secret: str
) -> bool:
    """Verifies `X-Muse-Signature: sha256=<hex>` in constant time."""
    clean_secret = (secret or "").strip()
    clean_sig = (signature_header or "").strip()
    if not clean_secret or not clean_sig.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        clean_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, clean_sig)


def process_muse_webhook_event(
    paths: AppPaths, payload: dict[str, Any]
) -> dict[str, Any]:
    """Processes `task.succeeded` / `task.failed` / `task.cancelled` idempotently."""
    event = str(payload.get("event") or "").strip()
    remote_task = payload.get("task")
    if not isinstance(remote_task, dict) or not remote_task.get("id"):
        return {"handled": False, "reason": "missing_task"}

    gw_id = str(remote_task["id"])
    local_task = get_muse_task_by_gateway_id(paths.db_file, gw_id)
    if local_task is None:
        return {"handled": False, "reason": "unknown_task"}

    # Idempotent guard: only act while task is actively submitted
    if local_task["status"] != "submitted":
        return {"handled": False, "reason": f"already_{local_task['status']}", "task_id": local_task["id"]}

    cfg = load_settings(paths.config_file).muse_gateway
    secrets = SecretsStore(paths.secrets_file)
    client = MuseGatewayClient(cfg, secrets)

    if event == "task.succeeded" or remote_task.get("status") == "succeeded":
        update_muse_task(paths.db_file, int(local_task["id"]), status="importing")
        done = import_completed_muse_task(paths, client, local_task, remote_task)
        run_downstream_hooks_for_task(paths, done)
        return {"handled": True, "status": "succeeded", "task_id": done["id"]}

    err_msg = str(remote_task.get("error") or event or "Muse task failed")
    failed = handle_remote_task_failure(paths, local_task, err_msg)
    run_downstream_hooks_for_task(paths, failed)
    return {"handled": True, "status": failed["status"], "task_id": failed["id"]}


__all__ = ["process_muse_webhook_event", "verify_muse_webhook_signature"]
