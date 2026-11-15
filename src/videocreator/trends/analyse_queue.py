"""Queues one `analyse_trend` job per trend item and tracks its status (queued/running/done/failed)."""
from __future__ import annotations

from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.jobs import PRIORITY_BACKGROUND, PRIORITY_PINNED, enqueue_job
from videocreator.paths import AppPaths

ANALYSE_TREND_JOB_KIND = "analyse_trend"


def set_analysis_status(paths: AppPaths, trend_item_id: int, status: str, error: str | None = None) -> None:
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE trend_items SET analysis_status = ?, analysis_error = ? WHERE id = ?",
            (status, error, trend_item_id),
        )


def _has_active_job(paths: AppPaths, trend_item_id: int) -> bool:
    row = query_one(
        paths.db_file,
        "SELECT 1 AS x FROM jobs WHERE kind = ? AND ref_id = ? AND status IN ('queued', 'running', 'waiting_quota') LIMIT 1",
        (ANALYSE_TREND_JOB_KIND, trend_item_id),
    )
    return row is not None


def other_analysis_jobs_pending(paths: AppPaths, trend_item_id: int) -> bool:
    """True while another `analyse_trend` job (not the one for `trend_item_id`) is still to run.

    A job waiting for AI quota does not count: it can wait for hours and must not hold back the
    suggestions of the rest of the batch (it makes its own when it finally ends)."""
    row = query_one(
        paths.db_file,
        """
        SELECT 1 AS x FROM jobs
        WHERE kind = ? AND status IN ('queued', 'running')
          AND COALESCE(ref_id, -1) != ?
        LIMIT 1
        """,
        (ANALYSE_TREND_JOB_KIND, trend_item_id),
    )
    return row is not None


def enqueue_trend_analysis(paths: AppPaths, trend_item_id: int) -> bool:
    """Queues analysis for one item. No-op (False) if it is analysed or already has a live job."""
    row = query_one(
        paths.db_file,
        "SELECT analysis_json, json_extract(metrics_json, '$.pinned') AS pinned FROM trend_items WHERE id = ?",
        (trend_item_id,),
    )
    if row is None or row.get("analysis_json"):
        return False
    if _has_active_job(paths, trend_item_id):
        return False
    priority = PRIORITY_PINNED if row.get("pinned") else PRIORITY_BACKGROUND
    enqueue_job(paths.db_file, ANALYSE_TREND_JOB_KIND, ref_id=trend_item_id, priority=priority)
    set_analysis_status(paths, trend_item_id, "queued")
    return True


def enqueue_top_trends(paths: AppPaths, *, top_n: int | None = None) -> list[int]:
    """Queues the best-scored unanalysed items of every source (skips ones that already failed)."""
    limit = top_n if top_n is not None else load_settings(paths.config_file).trends.auto_analyse_top_n
    queued: list[int] = []
    sources = query_all(paths.db_file, "SELECT DISTINCT source FROM trend_items ORDER BY source ASC")
    for s_row in sources:
        candidates = query_all(
            paths.db_file,
            """
            SELECT id FROM trend_items
            WHERE source = ? AND (analysis_json IS NULL OR analysis_json = '')
              AND COALESCE(analysis_status, '') != 'failed'
            ORDER BY score DESC, id ASC
            LIMIT ?
            """,
            (s_row["source"], max(0, limit)),
        )
        for c in candidates:
            if enqueue_trend_analysis(paths, int(c["id"])):
                queued.append(int(c["id"]))
    return queued
