"""Decisions on a trend suggestion: accept (plan videos from it) or dismiss."""
from __future__ import annotations
import logging
from pathlib import Path

from videocreator.config import load_settings
from videocreator.db import get_conn, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.plan_request import save_plan_request_params

logger = logging.getLogger("videocreator.trends.suggest")


def accept_suggestion(
    paths: AppPaths,
    suggestion_id: int,
    *,
    count: int = 1,
    auto_render: bool = False,
    actor: str = "ui",
) -> int | None:
    """Atomically accepts `suggestion_id` (`new`/`sent` -> `accepted`) and enqueues a `plan` job.

    Returns the enqueued `job_id`, or `None` if the suggestion was already accepted/dismissed.
    """
    row = query_one(
        paths.db_file,
        "SELECT * FROM suggestions WHERE id = ?",
        (suggestion_id,),
    )
    if row is None:
        raise LookupError(f"Suggestion #{suggestion_id} not found")

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            UPDATE suggestions
            SET status = 'accepted'
            WHERE id = ? AND status IN ('new', 'sent')
            """,
            (suggestion_id,),
        )
        if cur.rowcount != 1:
            return None
        record_audit(
            conn,
            actor=actor,
            action="suggestion.accepted",
            object_type="suggestion",
            object_id=suggestion_id,
            detail=f"count={count}, auto_render={auto_render}",
        )

    cfg = load_settings(paths.config_file)
    formula_obj = loads_or(row.get("formula_json"), {})

    # Use negative ref_id (-suggestion_id) so each suggestion's plan request file is isolated and uses library shots
    ref_key = -int(suggestion_id)
    save_plan_request_params(
        paths,
        ref_key,
        count=max(1, int(count)),
        voice_lang=cfg.telegram.default_voice_lang,
        caption_lang=cfg.telegram.default_caption_lang,
        target_duration_s=15.0,
        formula=formula_obj,
        suggestion_id=suggestion_id,
        auto_render=auto_render,
    )
    job_id = enqueue_job(paths.db_file, "plan", ref_id=ref_key)
    return job_id


def dismiss_suggestion(
    db_file: Path,
    suggestion_id: int,
    *,
    actor: str = "ui",
) -> bool:
    """Atomically transitions `suggestion_id` from `new`/`sent` to `dismissed`."""
    row = query_one(db_file, "SELECT id FROM suggestions WHERE id = ?", (suggestion_id,))
    if row is None:
        raise LookupError(f"Suggestion #{suggestion_id} not found")

    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            UPDATE suggestions
            SET status = 'dismissed'
            WHERE id = ? AND status IN ('new', 'sent')
            """,
            (suggestion_id,),
        )
        if cur.rowcount != 1:
            return False
        record_audit(
            conn,
            actor=actor,
            action="suggestion.dismissed",
            object_type="suggestion",
            object_id=suggestion_id,
        )
        return True
