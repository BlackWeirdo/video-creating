"""`trend_scan` job: scan every source, queue AI analysis for the best items, then suggest."""
from __future__ import annotations
from videocreator.paths import AppPaths
from videocreator.trends.analyse_queue import enqueue_top_trends
from videocreator.trends.scan import scan_all
from videocreator.trends.suggest import make_suggestions


def run_scan_and_suggest_job(paths: AppPaths, _ref_id: int = 0) -> str:
    """Runs trend scan -> queues one analysis job per top item -> suggestions for analysed ones.

    Analysis runs as separate `analyse_trend` jobs so a slow download or AI call never blocks
    the scan; the last job of the batch makes the suggestions. Only when nothing was queued
    (items already analysed earlier but without a suggestion yet) are suggestions made here.
    """
    scan_res = scan_all(paths)
    queued = enqueue_top_trends(paths)
    created_sugs = [] if queued else make_suggestions(paths)
    return (
        f"Scan upserted={scan_res['upserted']}, analysis queued={len(queued)}, "
        f"suggestions={len(created_sugs)}"
    )
