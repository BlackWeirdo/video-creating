"""`trend_scan` job: scan every source, then turn the best new items into suggestions."""
from __future__ import annotations
from videocreator.paths import AppPaths
from videocreator.trends.analyse import analyse_top_trends
from videocreator.trends.scan import scan_all
from videocreator.trends.suggest import make_suggestions


def run_scan_and_suggest_job(paths: AppPaths, _ref_id: int = 0) -> str:
    """Runs trend scan -> top-K structure analysis -> suggestion generation."""
    scan_res = scan_all(paths)
    analysed = analyse_top_trends(paths)
    created_sugs = make_suggestions(paths)
    return (
        f"Scan upserted={scan_res['upserted']}, analysed={len(analysed)}, "
        f"suggestions={len(created_sugs)}"
    )
