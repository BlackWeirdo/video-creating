"""Redo of a video: a new script for the replacement row, then its render (`FR-APR-05`, `FR-APR-06`)."""
from __future__ import annotations
import json
import logging
from typing import Any

from videocreator.ai.base import AIProvider
from videocreator.db import get_conn, query_one
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.planner import create_remix_plans

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
        s_row = query_one(paths.db_file, "SELECT formula_json FROM suggestions WHERE id = ?", (row["suggestion_id"],))
        try:
            formula = json.loads(str((s_row or {}).get("formula_json") or "null"))
        except ValueError:
            formula = None

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
        )
    except (ValueError, LookupError) as exc:
        note = "Làm lại: không tạo được kịch bản khác, dựng lại kịch bản cũ"
        logger.warning("Replan of video #%d kept the old plan: %s", video_id, exc)
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE videos SET quality_notes = ? WHERE id = ?", (note, video_id))
    enqueue_job(paths.db_file, "render", ref_id=video_id)
    return note or f"Replanned video #{video_id}"
