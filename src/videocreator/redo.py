"""Redo of a video (`FR-APR-05`, `FR-APR-06`): the old one is superseded, a replacement is planned."""
from __future__ import annotations

from pathlib import Path

from videocreator.db import get_conn, query_one
from videocreator.state import transition


def redo_video(
    db_file: Path,
    video_id: int,
    *,
    by: str = "ui",
    is_auto_retry: bool = False,
    max_retries: int = 2,
) -> int | None:
    """Marks `video_id` as `superseded` and queues a replacement with a NEW script (`FR-APR-05`, `FR-APR-06`).

    The replacement row starts with the old plan; the `replan` job writes a different one into it and
    renders it (re-rendering the same plan would give the same video). Studio videos are revised by
    prompt in Studio instead, so they return `None` here.

    `auto_retry_count` (auto quality scoring) and `redo_count` (human reviewer clicking 'Làm lại') are counted separately.
    Returns the new `video_id`, or `None` if the retry limit (`max_retries`, default 2) has been reached or the video was already superseded.
    """
    from videocreator.db import record_audit
    from videocreator.jobs import enqueue_job

    row = query_one(db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")

    cur_status = str(row["status"])
    if cur_status not in ("pending_approval", "rendered", "scoring", "planned"):
        return None
    if str(row.get("engine") or "") == "studio":
        return None

    cur_redo = int(row.get("redo_count") or 0)
    cur_auto = int(row.get("auto_retry_count") or 0)
    if is_auto_retry:
        if cur_auto >= max_retries:
            return None
        next_redo = cur_redo
        next_auto = cur_auto + 1
    else:
        if cur_redo >= max_retries:
            return None
        next_redo = cur_redo + 1
        next_auto = cur_auto

    if not transition(
        db_file,
        video_id,
        "superseded",
        expected_from=cur_status,
        actor=by,
    ):
        return None

    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (
                footage_id, product_ids_json, engine, status, plan_json,
                voice_lang, caption_lang, captions_json, target_accounts_json,
                redo_count, auto_retry_count, supersedes_id, suggestion_id, auto_render
            )
            VALUES (?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                row.get("footage_id"),
                row.get("product_ids_json") or "[]",
                row.get("engine") or "ffmpeg",
                row.get("plan_json") or "{}",
                row.get("voice_lang") or "none",
                row.get("caption_lang") or "vi",
                row.get("captions_json"),
                row.get("target_accounts_json"),
                next_redo,
                next_auto,
                video_id,
                row.get("suggestion_id"),
            ),
        )
        new_vid = int(cur.lastrowid or 0)
        record_audit(
            conn,
            actor=by,
            action="video.auto_retried" if is_auto_retry else "video.redone",
            object_type="video",
            object_id=new_vid,
            detail=f"supersedes={video_id}, redo={next_redo}, auto_retry={next_auto}",
        )

    enqueue_job(db_file, "replan", ref_id=new_vid)
    return new_vid
