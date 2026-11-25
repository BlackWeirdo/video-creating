"""Scheduled Autopilot tick execution across RSS, product A/B, suggestions, and trend localization."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.autopilot.crud import (
    get_autopilot_rule,
    hydrate_rule,
    validate_autopilot_policy,
)
from videocreator.autopilot.producers import ProducedItem, produce_autopilot_item
from videocreator.db import get_conn, query_all, query_one
from videocreator.job_store import report_active_job_progress
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now

logger = logging.getLogger("videocreator.autopilot")


def _count_today_runs(db_file: Path, rule_id: int, now_dt: datetime) -> int:
    day_start = now_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    row = query_one(
        db_file,
        """
        SELECT COUNT(*) AS c FROM autopilot_runs
        WHERE rule_id = ?
          AND created_at >= ?
          AND status IN ('scheduled', 'pending_review', 'completed')
        """,
        (int(rule_id), day_start),
    )
    return int(row["c"]) if row else 0


def _interval_due(rule: dict[str, Any], now_dt: datetime) -> bool:
    last_raw = str(rule.get("last_run_at") or "").strip()
    if not last_raw:
        return True
    try:
        last_dt = datetime.strptime(last_raw, UTC_ISO_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    elapsed_s = (now_dt.astimezone(timezone.utc) - last_dt).total_seconds()
    return elapsed_s >= max(1, int(rule.get("interval_minutes") or 60)) * 60


def _record_rule_result(
    db_file: Path,
    rule_id: int,
    *,
    now_iso: str,
    status: str,
    error: str | None = None,
    inc_generated: bool = False,
) -> None:
    inc_sql = ", total_generated = total_generated + 1" if inc_generated else ""
    with get_conn(db_file) as conn:
        conn.execute(
            f"""
            UPDATE autopilot_rules
            SET last_run_at = ?, last_status = ?, last_error = ? {inc_sql}
            WHERE id = ?
            """,
            (now_iso, status, error, int(rule_id)),
        )


def _execute_single_rule(
    paths: AppPaths,
    rule: dict[str, Any],
    *,
    force: bool = False,
    score_override: float | None = None,
    now_dt: datetime | None = None,
) -> dict[str, Any]:
    rule_id = int(rule["id"])
    ws_id = int(rule["workspace_id"])
    cur_now = utc_now(now_dt)
    now_iso = cur_now.strftime(UTC_ISO_FORMAT)

    if not force and not _interval_due(rule, cur_now):
        return {"rule_id": rule_id, "status": "cooldown", "video_id": None}

    if _count_today_runs(paths.db_file, rule_id, cur_now) >= int(rule["daily_cap"]):
        _record_rule_result(paths.db_file, rule_id, now_iso=now_iso, status="daily_cap_reached")
        return {"rule_id": rule_id, "status": "daily_cap_reached", "video_id": None}

    mode = str(rule["source_mode"])
    validate_autopilot_policy(paths.db_file, ws_id, mode)
    produced: ProducedItem | None = None

    try:
        report_active_job_progress(0.15, f"Autopilot #{rule_id}: đang quét nguồn {mode}...")
        produced = produce_autopilot_item(
            paths,
            rule,
            mode=mode,
            cur_now=cur_now,
            score_override=score_override,
        )

        if produced is None:
            _record_rule_result(paths.db_file, rule_id, now_iso=now_iso, status="no_new_items")
            return {"rule_id": rule_id, "status": "no_new_items", "video_id": None}

        if produced.video_id is None:
            raise RuntimeError("Autopilot generation produced no video output")

        video_id = produced.video_id
        v_row = query_one(
            paths.db_file,
            "SELECT quality_score, qc_json, status FROM videos WHERE id = ?",
            (video_id,),
        )
        assert v_row is not None
        qc = loads_or(v_row.get("qc_json"), {})
        if score_override is not None:
            eff_score = float(score_override)
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE videos SET quality_score = ? WHERE id = ?",
                    (eff_score, video_id),
                )
        else:
            eff_score = float(v_row.get("quality_score") or 0.0)

        scheduled = False
        min_req = float(rule.get("min_quality_score") or 8.0)
        if bool(qc.get("passed")) and eff_score >= min_req:
            scheduled = try_autopilot_approve(paths, video_id, now_dt=cur_now)

        run_status = "scheduled" if scheduled else "pending_review"
        detail = (
            f"video #{video_id} score={eff_score:.2f} (rule_min={min_req:.2f}) -> {run_status}"
        )
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                INSERT INTO autopilot_runs (
                    rule_id, workspace_id, source_key, source_summary,
                    video_id, batch_id, localize_id, status, detail
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    ws_id,
                    produced.source_key,
                    produced.source_summary,
                    video_id,
                    produced.batch_id,
                    produced.localize_id,
                    run_status,
                    detail,
                ),
            )
        _record_rule_result(
            paths.db_file,
            rule_id,
            now_iso=now_iso,
            status=run_status,
            error=None,
            inc_generated=True,
        )
        return {
            "rule_id": rule_id,
            "status": run_status,
            "video_id": video_id,
            "scheduled": scheduled,
            "quality_score": eff_score,
            "detail": detail,
        }
    except Exception as exc:
        logger.warning("Autopilot rule #%d failed: %s", rule_id, exc)
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                INSERT INTO autopilot_runs (
                    rule_id, workspace_id, source_key, source_summary,
                    video_id, batch_id, localize_id, status, detail
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'failed', ?)
                """,
                (
                    rule_id,
                    ws_id,
                    produced.source_key if produced else "",
                    produced.source_summary if produced else "",
                    produced.video_id if produced else None,
                    produced.batch_id if produced else None,
                    produced.localize_id if produced else None,
                    str(exc)[:400],
                ),
            )
        _record_rule_result(
            paths.db_file,
            rule_id,
            now_iso=now_iso,
            status="failed",
            error=str(exc)[:400],
        )
        return {
            "rule_id": rule_id,
            "status": "failed",
            "video_id": produced.video_id if produced else None,
            "error": str(exc),
        }


def run_autopilot_tick(
    paths: AppPaths,
    *,
    rule_id: int | None = None,
    force: bool = False,
    score_override: float | None = None,
    now_dt: datetime | None = None,
) -> list[dict[str, Any]]:
    """Execute one Autopilot tick for a single rule (`rule_id`) or all enabled rules."""
    if rule_id is not None:
        rule = get_autopilot_rule(paths.db_file, rule_id)
        if rule is None:
            raise ValueError(f"Autopilot rule #{rule_id} not found")
        if not rule["enabled"] and not force:
            return [{"rule_id": rule_id, "status": "disabled", "video_id": None}]
        return [
            _execute_single_rule(
                paths,
                rule,
                force=force,
                score_override=score_override,
                now_dt=now_dt,
            )
        ]

    rules = [
        hydrate_rule(r)
        for r in query_all(
            paths.db_file, "SELECT * FROM autopilot_rules WHERE enabled = 1 ORDER BY id ASC"
        )
    ]
    return [
        _execute_single_rule(
            paths,
            r,
            force=force,
            score_override=score_override,
            now_dt=now_dt,
        )
        for r in rules
    ]
