"""Status moves around a render: claiming the video, then scoring or sending it for approval."""
from __future__ import annotations

import logging
from typing import Any

from videocreator.db import get_conn, query_one
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import RenderError
from videocreator.state import transition

logger = logging.getLogger("videocreator.pipeline.render")


def claim_for_render(paths: AppPaths, video_id: int, cur_status: str) -> None:
    """Moves the video to `rendering`; a finished or failed video is first reset to `planned`."""
    if cur_status == "rendering":
        return
    if cur_status not in ("planned", "failed", "pending_approval", "rendered"):
        raise RenderError(f"Cannot render video #{video_id} from status '{cur_status}'")
    if cur_status != "planned":
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET status = 'planned', error = NULL WHERE id = ?",
                (video_id,),
            )
    transition(paths.db_file, video_id, "rendering", expected_from="planned", error=None)


def score_or_send_to_approval(
    paths: AppPaths,
    video_id: int,
    *,
    should_score: bool,
    score_provider: Any,
    score_override: float | None,
) -> int | None:
    """Moves a `rendered` video on. Returns the id of the video now waiting for approval (this one,
    or a better-scored earlier attempt), or None when a redo was queued instead."""
    if not should_score:
        transition(paths.db_file, video_id, "pending_approval", expected_from="rendered")
        return video_id
    from videocreator.pipeline.quality_score import score_rendered_video

    try:
        _status, active_id, _score = score_rendered_video(
            paths,
            video_id,
            provider=score_provider,
            score_override=score_override,
        )
        active = query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (active_id,))
        return active_id if active and str(active["status"]) == "pending_approval" else None
    except Exception as sc_exc:
        logger.warning("Auto quality score skipped for video #%d: %s", video_id, sc_exc)
        cur_row = query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (video_id,))
        cur_st = str(cur_row["status"]) if cur_row else "rendered"
        if cur_st in ("rendered", "scoring"):
            transition(paths.db_file, video_id, "pending_approval", expected_from=cur_st)
            return video_id
        return video_id if cur_st == "pending_approval" else None  # e.g. already superseded by a redo
