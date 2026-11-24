"""Atomic video approval and rejection service shared by Web UI and Telegram Bot (Phase 06)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from videocreator.config import ScheduleConfig, load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.posting.slots import assign_auto_slots_for_video, default_target_account_ids
from videocreator.state import InvalidTransitionError, transition


def validate_video_policy_for_approval(db_file: Path, video_id: int) -> list[str]:
    """Checks workspace `content_policy` (`strict_footage` blocks unverified claims & non-footage product shots)."""
    row = query_one(
        db_file,
        """
        SELECT v.workspace_id, v.unsupported_claims_json, v.plan_json,
               COALESCE(w.content_policy, 'strict_footage') AS content_policy
        FROM videos v
        LEFT JOIN workspaces w ON v.workspace_id = w.id
        WHERE v.id = ?
        """,
        (video_id,),
    )
    if row is None:
        return [f"Video #{video_id} not found"]

    policy = str(row.get("content_policy") or "strict_footage")
    if policy != "strict_footage":
        return []

    violations: list[str] = []
    claims = loads_or(row.get("unsupported_claims_json"), [])
    if isinstance(claims, list) and any(str(c).strip() for c in claims):
        violations.append(
            f"Workspace strict_footage từ chối duyệt: video #{video_id} còn {len(claims)} tuyên bố chưa kiểm chứng"
        )

    plan = loads_or(row.get("plan_json"), {})
    if isinstance(plan, dict):
        if plan.get("ai_generated_product") is True:
            violations.append(
                f"Workspace strict_footage từ chối duyệt: video #{video_id} dùng hình AI cho sản phẩm"
            )
        shot_ids = sorted(
            {
                int(s.get("shot_id") or 0)
                for s in (plan.get("shots") or [])
                if isinstance(s, dict) and int(s.get("shot_id") or 0) > 0
            }
        )
        if shot_ids:
            shots = query_all(
                db_file,
                f"SELECT id, footage_id, has_product FROM shots WHERE id IN ({','.join('?' * len(shot_ids))})",
                shot_ids,
            )
            bad_shots = [
                int(s["id"])
                for s in shots
                if int(s.get("has_product") or 0) == 1 and s.get("footage_id") is None
            ]
            if bad_shots:
                violations.append(
                    f"Workspace strict_footage từ chối duyệt: shot {bad_shots} có sản phẩm nhưng không gắn footage thật"
                )
    return violations


def approve(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    target_account_ids: list[int] | None = None,
    config_file: Path | None = None,
    now_dt: datetime | None = None,
    auto_schedule: bool | None = None,
    enforce_policy: bool = False,
) -> bool:
    """Atomically transitions `video_id` from `pending_approval` to `approved` (and `scheduled` if auto-slot is enabled).

    `enforce_policy=True` rejects videos violating `strict_footage` (used by `bulk_approve` & `autopilot`).
    """
    row = query_one(db_file, "SELECT status FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")
    cur_status = str(row["status"])
    if cur_status in ("approved", "rejected", "scheduled", "posted", "partially_posted"):
        return False
    if cur_status != "pending_approval":
        raise InvalidTransitionError(
            f"Cannot approve video #{video_id} from status '{cur_status}' (must be 'pending_approval')"
        )

    if enforce_policy:
        violations = validate_video_policy_for_approval(db_file, video_id)
        if violations:
            raise ValueError("; ".join(violations))

    won = transition(
        db_file,
        video_id,
        "approved",
        expected_from="pending_approval",
        actor=by,
        approved_by=by,
    )
    if won and target_account_ids is not None:
        clean_acc = sorted({int(a) for a in target_account_ids if int(a) > 0})
        with get_conn(db_file) as conn:
            conn.execute(
                "UPDATE videos SET target_accounts_json = ? WHERE id = ?",
                (json.dumps(clean_acc), video_id),
            )

    if won:
        sched_cfg = (
            load_settings(config_file).schedule
            if (config_file is not None and config_file.exists())
            else ScheduleConfig()
        )
        should_auto = sched_cfg.auto if auto_schedule is None else auto_schedule
        if should_auto:
            assign_auto_slots_for_video(
                db_file,
                video_id,
                config_file=config_file,
                account_ids=target_account_ids,
                now_dt=now_dt,
                actor=by,
            )
    return won


def reject(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    reason: str | None = None,
) -> bool:
    """Atomically transitions `video_id` from `pending_approval` to `rejected`."""
    row = query_one(db_file, "SELECT status FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")
    cur_status = str(row["status"])
    if cur_status in ("approved", "rejected", "scheduled", "posted", "partially_posted"):
        return False
    if cur_status != "pending_approval":
        raise InvalidTransitionError(
            f"Cannot reject video #{video_id} from status '{cur_status}' (must be 'pending_approval')"
        )

    return transition(
        db_file,
        video_id,
        "rejected",
        expected_from="pending_approval",
        actor=by,
        approved_by=by,
        reject_reason=(reason or "").strip() or None,
    )


def post_now(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    now_dt: datetime | None = None,
) -> list[int]:
    """Approves `video_id` (if `pending_approval`) and schedules all target accounts for immediate publishing (`scheduled_at = now`)."""
    from videocreator.posting.service import schedule_approved_video
    from videocreator.timeutil import utc_now_iso

    row = query_one(db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")

    if str(row["status"]) == "pending_approval":
        approve(db_file, video_id, by=by, auto_schedule=False)

    target_ids = default_target_account_ids(db_file, video_id)
    if not target_ids:
        return []

    now_iso = utc_now_iso(now_dt)
    post_ids = schedule_approved_video(
        db_file,
        video_id,
        account_ids=target_ids,
        scheduled_at_iso=now_iso,
        actor=by,
    )
    with get_conn(db_file) as conn:
        conn.execute(
            "UPDATE posts SET scheduled_at = ? WHERE video_id = ? AND status = 'scheduled'",
            (now_iso, video_id),
        )
    return post_ids


def bulk_approve(
    db_file: Path,
    video_ids: list[int],
    *,
    by: str = "ui",
    target_account_ids: list[int] | None = None,
    config_file: Path | None = None,
    now_dt: datetime | None = None,
    auto_schedule: bool | None = None,
    enforce_policy: bool = True,
) -> dict[str, Any]:
    """Approves multiple `pending_approval` videos sequentially so auto-slots never collide."""
    approved_ids: list[int] = []
    skipped_ids: list[int] = []
    errors: dict[str, str] = {}

    seen: set[int] = set()
    for raw_id in video_ids:
        vid = int(raw_id)
        if vid <= 0 or vid in seen:
            continue
        seen.add(vid)
        try:
            won = approve(
                db_file,
                vid,
                by=by,
                target_account_ids=target_account_ids,
                config_file=config_file,
                now_dt=now_dt,
                auto_schedule=auto_schedule,
                enforce_policy=enforce_policy,
            )
            if won:
                approved_ids.append(vid)
            else:
                skipped_ids.append(vid)
        except Exception as exc:
            errors[str(vid)] = str(exc)

    return {
        "approved_ids": approved_ids,
        "skipped_ids": skipped_ids,
        "errors": errors,
    }


def resolve_effective_approval_mode(
    db_file: Path, video_id: int
) -> tuple[str, float]:
    """Resolves effective approval mode (`single`|`bulk`|`autopilot`) & min autopilot QC score."""
    row = query_one(
        db_file,
        """
        SELECT v.workspace_id, COALESCE(w.approval_mode, 'single') AS ws_approval_mode
        FROM videos v
        LEFT JOIN workspaces w ON v.workspace_id = w.id
        WHERE v.id = ?
        """,
        (video_id,),
    )
    if row is None:
        return "single", 8.0
    ws_mode = str(row.get("ws_approval_mode") or "single")
    target_ids = default_target_account_ids(db_file, video_id)
    if not target_ids:
        return ws_mode, 8.0

    acc_rows = query_all(
        db_file,
        f"SELECT approval_mode, autopilot_min_score FROM accounts WHERE id IN ({','.join('?' * len(target_ids))})",
        target_ids,
    )
    if not acc_rows:
        return ws_mode, 8.0

    resolved_modes: set[str] = set()
    min_score = 8.0
    for acc in acc_rows:
        raw_mode = str(acc.get("approval_mode") or "inherit")
        eff = ws_mode if raw_mode == "inherit" else raw_mode
        resolved_modes.add(eff)
        if acc.get("autopilot_min_score") is not None:
            min_score = max(min_score, float(acc["autopilot_min_score"]))

    if "single" in resolved_modes:
        return "single", min_score
    if "bulk" in resolved_modes:
        return "bulk", min_score
    if resolved_modes == {"autopilot"}:
        return "autopilot", min_score
    return ws_mode, min_score


def try_autopilot_approve(
    paths: AppPaths,
    video_id: int,
    *,
    now_dt: datetime | None = None,
) -> bool:
    """Auto-approves & schedules `video_id` ONLY when `autopilot` is enabled and QC/policy/score gates pass."""
    v_row = query_one(
        paths.db_file,
        "SELECT status, qc_json, preflight_json, quality_score FROM videos WHERE id = ?",
        (video_id,),
    )
    if v_row is None or str(v_row.get("status") or "") != "pending_approval":
        return False

    eff_mode, min_score = resolve_effective_approval_mode(paths.db_file, video_id)
    if eff_mode != "autopilot":
        return False

    if validate_video_policy_for_approval(paths.db_file, video_id):
        return False

    qc = loads_or(v_row.get("qc_json"), {})
    if not isinstance(qc, dict) or qc.get("passed") is not True:
        return False

    q_score = v_row.get("quality_score")
    if q_score is None or float(q_score) < min_score:
        return False

    target_ids = default_target_account_ids(paths.db_file, video_id)
    if not target_ids:
        return False

    preflight = loads_or(v_row.get("preflight_json"), {})
    acc_rows = query_all(
        paths.db_file,
        f"SELECT platform FROM accounts WHERE id IN ({','.join('?' * len(target_ids))})",
        target_ids,
    )
    for acc in acc_rows:
        plat = str(acc.get("platform") or "")
        if isinstance(preflight, dict) and preflight.get(plat):
            return False

    return approve(
        paths.db_file,
        video_id,
        by="autopilot",
        target_account_ids=target_ids,
        config_file=paths.config_file,
        now_dt=now_dt,
        auto_schedule=True,
    )
