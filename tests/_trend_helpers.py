"""Shared helpers for trend analysis tests (real sqlite, no mocks)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI

from videocreator.app import create_app
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.trends.analyse_queue import ANALYSE_TREND_JOB_KIND
from videocreator.trends.base import TrendItem
from videocreator.trends.scan import upsert_trend_item

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def _make_app(tmp_path: Path) -> tuple[FastAPI, AppPaths]:
    app = create_app(data_dir=tmp_path, start_worker=False)
    return app, app.state.paths


def _add_item(paths: AppPaths, source: str, ext: str, score: float) -> int:
    item = TrendItem(
        source=source, external_id=ext, url=f"https://example.com/{source}/{ext}",
        author=f"author-{ext}", caption=f"caption {ext}", published_at=NOW,
        metrics={"views": 100},
    )
    tid = upsert_trend_item(paths.db_file, item, now_dt=NOW)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE trend_items SET score = ? WHERE id = ?", (score, tid))
    return tid


def _jobs(paths: AppPaths, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM jobs WHERE kind = ?"
    args: tuple = (ANALYSE_TREND_JOB_KIND,)
    if status:
        sql += " AND status = ?"
        args += (status,)
    return query_all(paths.db_file, sql + " ORDER BY id", args)


def _status(paths: AppPaths, tid: int) -> str | None:
    return query_one(paths.db_file, "SELECT analysis_status AS s FROM trend_items WHERE id = ?", (tid,))["s"]


def _mark_analysed(paths: AppPaths, tid: int) -> None:
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE trend_items SET analysis_json = '{\"hook\": \"h\"}' WHERE id = ?", (tid,))
