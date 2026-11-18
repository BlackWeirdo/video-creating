"""Redo of a video: a new script for the replacement row, then its render (`FR-APR-05`, `FR-APR-06`)."""
from __future__ import annotations
import logging
from typing import Any

from videocreator.ai.base import AIProvider
from videocreator.db import get_conn, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.planner import create_remix_plans
from videocreator.state import transition
from videocreator.trends.suggestion_formula import load_suggestion_formula

logger = logging.getLogger("videocreator.pipeline.planner")


def _restore_best_on_auto_replan_failure(
    paths: AppPaths,
    video_id: int,
    parent_id: int,
    reason: str,
) -> str:
    from videocreator.pipeline.quality_score import best_in_chain
    from videocreator.tg.approval_notify import notify_pending

    note = f"Không thể tự làm lại (không tạo được kịch bản khác biệt): {reason}"
    best_id = best_in_chain(paths, parent_id)
    with get_conn(paths.db_file) as conn:
        transition(conn, video_id, "superseded", expected_from="planned", actor="auto_quality", error=note)
        conn.execute("UPDATE videos SET quality_notes = ? WHERE id = ?", (note, video_id))
        restored = transition(conn, best_id, "pending_approval", expected_from="superseded", actor="auto_quality")
        if restored:
            best_row = conn.execute("SELECT quality_notes FROM videos WHERE id = ?", (best_id,)).fetchone()
            existing_notes = str(best_row["quality_notes"] or "").strip() if best_row else ""
            suffix = "Không thể tự làm lại (không tạo được kịch bản khác biệt)"
            combined = f"{existing_notes} | {suffix}" if existing_notes and suffix not in existing_notes else (existing_notes or suffix)
            conn.execute("UPDATE videos SET quality_notes = ? WHERE id = ?", (combined, best_id))
            record_audit(
                conn,
                actor="auto_quality",
                action="video.best_attempt_restored",
                object_type="video",
                object_id=best_id,
                detail=f"replan_failed_on=#{video_id}",
            )
    if restored:
        try:
            notify_pending(paths, best_id)
        except Exception as tg_exc:
            logger.warning("notify_pending hook warning for restored video #%d: %s", best_id, tg_exc)
    return note


def replan_video(
    paths: AppPaths,
    video_id: int,
    *,
    writer_provider: AIProvider | None = None,
    checker_provider: AIProvider | None = None,
) -> str:
    """Job handler for `replan` (redo, `FR-APR-05`, `FR-APR-06`): gives the replacement video a new
    script, then queues its render. If no different valid script can be produced, never re-renders
    the identical old script."""
    from videocreator.jobs import enqueue_job

    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")
    if str(row["status"]) != "planned":
        return f"Video #{video_id} is '{row['status']}', nothing to replan"
    old_plan = loads_or(row.get("plan_json"), {})
    formula: dict[str, Any] | None = None
    if row.get("suggestion_id"):
        formula = load_suggestion_formula(paths.db_file, int(row["suggestion_id"]))

    # The attempt this one replaces: why it scored low, so the new script fixes exactly that.
    fix_hint: str | None = None
    parent: dict[str, Any] | None = None
    if row.get("supersedes_id"):
        parent = query_one(
            paths.db_file,
            "SELECT id, quality_score, quality_notes, auto_retry_count, redo_count FROM videos WHERE id = ?",
            (row["supersedes_id"],),
        )
        if parent and parent.get("quality_score") is not None and parent.get("quality_notes"):
            fix_hint = str(parent["quality_notes"])[:400]

    try:
        create_remix_plans(
            paths,
            row.get("footage_id"),
            voice_lang=str(row.get("voice_lang") or "none"),  # type: ignore[arg-type]
            caption_lang=str(row.get("caption_lang") or "vi"),  # type: ignore[arg-type]
            target_duration_s=float(old_plan.get("total_duration_s") or 15.0),
            formula=formula,
            suggestion_id=row.get("suggestion_id"),
            writer_provider=writer_provider,
            checker_provider=checker_provider,
            replace_video_id=video_id,
            fix_hint=fix_hint,
        )
    except (ValueError, LookupError) as exc:
        is_auto_retry = parent is not None and (
            int(row.get("auto_retry_count") or 0) > int(parent.get("auto_retry_count") or 0)
            and int(row.get("redo_count") or 0) == int(parent.get("redo_count") or 0)
        )
        if is_auto_retry and parent is not None:
            logger.warning("Auto-replan of video #%d could not produce a distinct script: %s", video_id, exc)
            return _restore_best_on_auto_replan_failure(paths, video_id, int(parent["id"]), str(exc))

        note = f"Không thể làm lại (không tạo được kịch bản mới khác kịch bản cũ): {exc}"
        logger.warning("Replan of video #%d aborted (refusing to re-render identical script): %s", video_id, exc)
        with get_conn(paths.db_file) as conn:
            transition(conn, video_id, "failed", expected_from="planned", actor="worker", error=note)
            conn.execute("UPDATE videos SET quality_notes = ? WHERE id = ?", (note, video_id))
        try:
            from videocreator.tg.sender import send_text

            send_text(paths, f"⚠️ Video #{video_id}: {note}", respect_quiet_hours=True, topic="ops")
        except Exception as tg_exc:
            logger.debug("replan failure notify skipped: %s", tg_exc)
        return note

    enqueue_job(paths.db_file, "render", ref_id=video_id)
    return f"Replanned video #{video_id}"
