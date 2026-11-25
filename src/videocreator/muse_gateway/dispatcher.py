"""Non-blocking multi-lane dispatcher polling, submitting, and importing `muse_tasks`."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from videocreator.config import load_settings
from videocreator.muse_gateway.capacity import (
    compute_gateway_capacity,
    is_daily_account_cap_reached,
    next_local_midnight_utc_iso,
)
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import (
    MuseGatewayError,
    MuseInputError,
    MuseQuotaWait,
)
from videocreator.muse_gateway.media_import import import_completed_muse_task
from videocreator.muse_gateway.refs import resolve_task_refs_to_data_urls
from videocreator.muse_gateway.store import (
    list_tasks_by_status,
    select_fair_pending_tasks,
    update_muse_task,
    wake_expired_muse_quota_tasks,
)
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.timeutil import UTC_ISO_FORMAT, parse_iso_utc, utc_now, utc_now_iso

logger = logging.getLogger("videocreator.muse_gateway.dispatcher")

DownstreamHook = Callable[[AppPaths, dict[str, Any]], None]
_DOWNSTREAM_HOOKS: list[DownstreamHook] = []
_DISPATCH_LOCKS: dict[Path, threading.Lock] = {}
_LOCK_GUARD = threading.Lock()


def register_muse_downstream_hook(hook: DownstreamHook) -> None:
    if hook not in _DOWNSTREAM_HOOKS:
        _DOWNSTREAM_HOOKS.append(hook)


def run_downstream_hooks_for_task(paths: AppPaths, task_row: dict[str, Any]) -> None:
    import videocreator.muse_gateway.storyboard  # noqa: F401
    import videocreator.muse_gateway.studio_bridge  # noqa: F401

    for hook in list(_DOWNSTREAM_HOOKS):
        try:
            hook(paths, task_row)
        except Exception as exc:
            logger.error("Muse downstream hook failed for task #%s: %s", task_row.get("id"), exc, exc_info=True)


def _lock_for(data_dir: Path) -> threading.Lock:
    key = data_dir.resolve()
    with _LOCK_GUARD:
        lk = _DISPATCH_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _DISPATCH_LOCKS[key] = lk
        return lk


def _utc_iso_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(30, int(seconds)))).strftime(
        UTC_ISO_FORMAT
    )


def _fetch_local_pool_state(base_url: str) -> dict[str, Any] | None:
    try:
        resp = httpx.get(f"{base_url}/api/pool", timeout=6.0, trust_env=False)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, dict) else None
    except httpx.RequestError:
        pass
    return None


def handle_remote_task_failure(
    paths: AppPaths,
    task_row: dict[str, Any],
    error_msg: str,
    *,
    cooldown_s: int = 1800,
) -> dict[str, Any]:
    """Applies retry-with-new-idempotency-key on transient/restart errors, or parks on quota."""
    cfg = load_settings(paths.config_file).muse_gateway
    tid = int(task_row["id"])
    attempt = int(task_row.get("attempt") or 0)
    lower = (error_msg or "").lower()

    if any(k in lower for k in ("quota", "rate limit", "429", "cooldown", "limit reached")):
        res = update_muse_task(
            paths.db_file,
            tid,
            status="waiting_quota",
            gateway_task_id=None,
            error=error_msg[:400],
            retry_after=_utc_iso_after(cooldown_s),
        )
        assert res is not None
        return res

    is_transient = any(
        k in lower
        for k in ("restarted", "browser", "timeout", "timed out", "navigation", "502", "503", "504")
    )
    if is_transient and (attempt + 1) < int(cfg.max_attempts):
        res = update_muse_task(
            paths.db_file,
            tid,
            status="pending",
            attempt=attempt + 1,
            gateway_task_id=None,
            idempotency_key=None,
            error=f"Thử lại lần {attempt + 1}: {error_msg[:300]}",
        )
        assert res is not None
        return res

    res = update_muse_task(
        paths.db_file,
        tid,
        status="failed",
        error=error_msg[:500],
        finished_at=utc_now_iso(),
    )
    assert res is not None
    return res


def _build_gateway_submit_payload(
    paths: AppPaths,
    task_row: dict[str, Any],
    *,
    webhook_url: str | None,
    webhook_secret: str | None,
) -> dict[str, Any]:
    params = dict(task_row.get("params") or {})
    refs = list(task_row.get("refs") or [])
    ws_id = int(task_row["workspace_id"])
    tid = int(task_row["id"])
    attempt = int(task_row.get("attempt") or 0)
    idem = f"vc-{ws_id}-{tid}-a{attempt}"

    payload: dict[str, Any] = {
        "model": str(task_row["model"]),
        "prompt": str(task_row["prompt"]),
        "idempotency_key": idem,
        "new_chat": bool(params.get("new_chat", True)),
    }
    if params.get("duration") is not None:
        payload["duration"] = int(params["duration"])
    if params.get("ratio"):
        payload["ratio"] = str(params["ratio"])
    if params.get("count") is not None:
        payload["count"] = int(params["count"])
    if params.get("voice"):
        payload["voice"] = str(params["voice"])
    if params.get("language"):
        payload["language"] = str(params["language"])
    if params.get("speed") is not None:
        payload["speed"] = float(params["speed"])

    thread = str(task_row.get("thread_url") or params.get("thread") or "").strip()
    account = str(task_row.get("account_id") or params.get("account") or "").strip()
    if thread and account:
        payload["thread"] = thread
        payload["account"] = account
        payload["new_chat"] = False

    if refs:
        payload["images"] = resolve_task_refs_to_data_urls(paths, workspace_id=ws_id, refs=refs)

    if webhook_url and webhook_secret:
        payload["webhook_url"] = webhook_url
        payload["webhook_secret"] = webhook_secret
    return payload


def run_muse_dispatcher_tick(
    paths: AppPaths,
    *,
    webhook_base_url: str | None = None,
) -> dict[str, Any]:
    """Single non-blocking tick: wakes quota tasks, batch-polls submitted tasks, submits up to free capacity."""
    settings = load_settings(paths.config_file)
    cfg = settings.muse_gateway
    if not cfg.enabled:
        return {"enabled": False, "submitted_now": 0, "completed_now": 0}

    lk = _lock_for(paths.data_dir)
    if not lk.acquire(blocking=False):
        return {"enabled": True, "busy": True, "submitted_now": 0, "completed_now": 0}

    try:
        now_dt = utc_now()
        now_iso = now_dt.strftime(UTC_ISO_FORMAT)
        woken = wake_expired_muse_quota_tasks(paths.db_file, now_iso)

        secrets = SecretsStore(paths.secrets_file)
        client = MuseGatewayClient(cfg, secrets)
        try:
            client.verify_ready_and_safe()
        except MuseGatewayError as exc:
            return {"enabled": True, "online": False, "error": str(exc), "woken": woken}

        pool_state = _fetch_local_pool_state(client.base_url) if cfg.mode == "local_sidecar" else None
        disc_info = None
        if pool_state is None:
            try:
                disc_info = client.discover()
            except MuseGatewayError:
                disc_info = None
        cap_info = compute_gateway_capacity(pool_state, cfg, discover_info=disc_info)

        # 1. Batch poll currently submitted tasks
        completed_now = 0
        submitted_rows = list_tasks_by_status(paths.db_file, "submitted")
        if submitted_rows:
            remote_list = client.list_tasks(limit=100)
            remote_map = {str(r["id"]): r for r in remote_list if r.get("id")}
            for row in submitted_rows:
                tid = int(row["id"])
                gw_id = str(row.get("gateway_task_id") or "")
                rem = remote_map.get(gw_id)
                if rem is None and gw_id:
                    try:
                        rem = client.get_task(gw_id)
                    except MuseInputError:
                        updated = handle_remote_task_failure(paths, row, "Gateway restarted or task evicted (404)")
                        run_downstream_hooks_for_task(paths, updated)
                        continue
                    except MuseGatewayError:
                        continue
                if rem is None:
                    continue

                rem_status = str(rem.get("status") or "running")
                if rem_status in ("queued", "running"):
                    sub_dt = parse_iso_utc(row.get("submitted_at"))
                    if sub_dt and (now_dt - sub_dt).total_seconds() > int(cfg.task_timeout_min) * 60:
                        try:
                            client.cancel_task(gw_id)
                        except MuseGatewayError:
                            pass
                        updated = handle_remote_task_failure(
                            paths, row, f"Timed out after {cfg.task_timeout_min} minutes"
                        )
                        run_downstream_hooks_for_task(paths, updated)
                    continue

                if rem_status == "succeeded":
                    update_muse_task(paths.db_file, tid, status="importing")
                    try:
                        done = import_completed_muse_task(paths, client, row, rem)
                        completed_now += 1
                        run_downstream_hooks_for_task(paths, done)
                    except Exception as exc:
                        failed = handle_remote_task_failure(paths, row, f"Media import failed: {exc}")
                        run_downstream_hooks_for_task(paths, failed)
                elif rem_status in ("failed", "cancelled"):
                    err_txt = str(rem.get("error") or f"Gateway marked task {rem_status}")
                    updated = handle_remote_task_failure(
                        paths,
                        row,
                        err_txt,
                        cooldown_s=int(cap_info["earliest_cooldown_s"]),
                    )
                    run_downstream_hooks_for_task(paths, updated)

        # 2. Submit pending tasks up to available capacity slots
        still_submitted = len(list_tasks_by_status(paths.db_file, "submitted"))
        free_slots = max(0, int(cap_info["capacity"]) - still_submitted)
        submitted_now = 0

        if int(cap_info["capacity"]) == 0 and int(cap_info["cooling_accounts"]) > 0:
            # All enabled accounts are cooling down: park top pending tasks into waiting_quota
            for p_row in select_fair_pending_tasks(paths.db_file, limit=20):
                update_muse_task(
                    paths.db_file,
                    int(p_row["id"]),
                    status="waiting_quota",
                    retry_after=_utc_iso_after(int(cap_info["earliest_cooldown_s"])),
                    error="Tất cả tài khoản Muse đang nghỉ chờ hồi hạn mức (cooldown).",
                )
        elif free_slots > 0:
            wh_url: str | None = None
            wh_sec: str | None = None
            if cfg.mode == "local_sidecar" and cfg.use_webhook:
                eff_api = (webhook_base_url or f"http://127.0.0.1:{settings.port}").rstrip("/")
                wh_sec = (secrets.get("MUSE_GATEWAY_WEBHOOK_SECRET") or "").strip() or None
                if wh_sec:
                    wh_url = f"{eff_api}/api/v1/integrations/muse/webhook"

            candidates = select_fair_pending_tasks(paths.db_file, limit=free_slots)
            for cand in candidates:
                tid = int(cand["id"])
                kind = str(cand["kind"])
                if is_daily_account_cap_reached(
                    paths.db_file,
                    cfg,
                    kind=kind,
                    eligible_accounts=max(1, int(cap_info["eligible_accounts"])),
                ):
                    update_muse_task(
                        paths.db_file,
                        tid,
                        status="waiting_quota",
                        retry_after=next_local_midnight_utc_iso(paths.db_file),
                        error=f"Đã đạt trần an toàn/ngày cho loại '{kind}'; tự chạy tiếp sau 00:05.",
                    )
                    continue

                try:
                    payload = _build_gateway_submit_payload(
                        paths, cand, webhook_url=wh_url, webhook_secret=wh_sec
                    )
                    created = client.create_task(payload)
                    update_muse_task(
                        paths.db_file,
                        tid,
                        status="submitted",
                        gateway_task_id=str(created["id"]),
                        idempotency_key=str(payload["idempotency_key"]),
                        submitted_at=utc_now_iso(),
                        error=None,
                    )
                    submitted_now += 1
                except MuseQuotaWait as q_exc:
                    update_muse_task(
                        paths.db_file,
                        tid,
                        status="waiting_quota",
                        retry_after=_utc_iso_after(q_exc.retry_after_s),
                        error=str(q_exc)[:400],
                    )
                except (MuseInputError, PermissionError) as in_exc:
                    failed = update_muse_task(
                        paths.db_file,
                        tid,
                        status="failed",
                        error=str(in_exc)[:500],
                        finished_at=utc_now_iso(),
                    )
                    if failed:
                        run_downstream_hooks_for_task(paths, failed)
                except MuseGatewayError as gw_exc:
                    updated = handle_remote_task_failure(paths, cand, str(gw_exc))
                    run_downstream_hooks_for_task(paths, updated)

        return {
            "enabled": True,
            "online": True,
            "capacity": cap_info["capacity"],
            "submitted_now": submitted_now,
            "completed_now": completed_now,
            "woken": woken,
        }
    finally:
        lk.release()


__all__ = [
    "handle_remote_task_failure",
    "register_muse_downstream_hook",
    "run_downstream_hooks_for_task",
    "run_muse_dispatcher_tick",
]
