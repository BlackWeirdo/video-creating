"""Redo of a video: a new script for the replacement row, then its render (`FR-APR-05`, `FR-APR-06`)."""
from __future__ import annotations
import logging
from typing import Any

from videocreator.ai.base import AIProvider
from videocreator.db import get_conn, query_one
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.planner import create_remix_plans
from videocreator.trends.suggestion_formula import load_suggestion_formula

logger = logging.getLogger("videocreator.pipeline.planner")


def replan_video(
    paths: AppPaths,
    video_id: int,
    *,
    writer_provider: AIProvider | None = None,
    checker_provider: AIProvider | None = None,
) -> str:
    """Job handler for `replan` (redo, `FR-APR-05`, `FR-APR-06`): gives the replacement video a new
    script, then queues its render. If no different valid script comes out, the old one is rendered
    again and the reviewer is told so."""
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
    if row.get("supersedes_id"):
        parent = query_one(
            paths.db_file, "SELECT quality_score, quality_notes FROM videos WHERE id = ?", (row["supersedes_id"],)
        )
        if parent and parent.get("quality_score") is not None and parent.get("quality_notes"):
            fix_hint = str(parent["quality_notes"])[:400]

    note = ""
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
        note = "Làm lại: không tạo được kịch bản khác, dựng lại kịch bản cũ"
        logger.warning("Replan of video #%d kept the old plan: %s", video_id, exc)
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE videos SET quality_notes = ? WHERE id = ?", (note, video_id))
    enqueue_job(paths.db_file, "render", ref_id=video_id)
    return note or f"Replanned video #{video_id}"
