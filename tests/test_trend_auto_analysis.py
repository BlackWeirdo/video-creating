"""Auto trend analysis queue, routes, template states, migration 011 and job failure path.

Real SQLite in tmp_path, real jobs table, real FastAPI app. No network, no AI calls, no mocks.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from videocreator.ai.base import AIError
from videocreator.config import load_settings, save_settings
from videocreator.db import DEFAULT_MIGRATIONS_DIR, get_conn, migrate, query_all, query_one
from videocreator.trends.analyse_queue import enqueue_top_trends, enqueue_trend_analysis
from videocreator.trends.links import run_analyse_trend_job
from _trend_helpers import _add_item, _jobs, _make_app, _mark_analysed, _status


@pytest.mark.local
def test_enqueue_top_trends_top_n_per_source_by_score_skips_analysed(tmp_path: Path) -> None:
    _app, paths = _make_app(tmp_path)
    y = {s: _add_item(paths, "youtube", f"y{s}", s) for s in (1, 5, 3, 9)}
    t = {s: _add_item(paths, "tiktok", f"t{s}", s) for s in (2, 8)}
    _mark_analysed(paths, y[9])  # best youtube item already analysed -> skipped, next 2 are taken

    queued = enqueue_top_trends(paths, top_n=2)

    assert sorted(queued) == sorted([y[5], y[3], t[8], t[2]])
    assert _status(paths, y[5]) == "queued" and _status(paths, y[3]) == "queued"
    assert _status(paths, y[1]) is None and _status(paths, y[9]) is None
    jobs = _jobs(paths)
    assert sorted(j["ref_id"] for j in jobs) == sorted(queued)
    assert {j["status"] for j in jobs} == {"queued"}


@pytest.mark.local
def test_enqueue_is_idempotent_and_requeues_stale_items(tmp_path: Path) -> None:
    _app, paths = _make_app(tmp_path)
    a = _add_item(paths, "youtube", "a", 5)
    b = _add_item(paths, "youtube", "b", 4)

    assert sorted(enqueue_top_trends(paths, top_n=5)) == sorted([a, b])
    assert enqueue_top_trends(paths, top_n=5) == []
    assert len(_jobs(paths)) == 2
    assert enqueue_trend_analysis(paths, a) is False  # live job exists

    # Job for `a` ended without updating the trend (status still 'queued'): stale -> re-queued.
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE jobs SET status = 'done' WHERE ref_id = ?", (a,))
        conn.execute("UPDATE jobs SET status = 'failed' WHERE ref_id = ?", (b,))
    assert _status(paths, a) == "queued"
    assert sorted(enqueue_top_trends(paths, top_n=5)) == sorted([a, b])
    assert len(_jobs(paths, "queued")) == 2
    assert len(_jobs(paths)) == 4


@pytest.mark.local
def test_failed_items_skipped_by_top_but_retry_requeues(tmp_path: Path) -> None:
    _app, paths = _make_app(tmp_path)
    a = _add_item(paths, "youtube", "a", 5)
    b = _add_item(paths, "youtube", "b", 4)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE trend_items SET analysis_status = 'failed', analysis_error = 'x' WHERE id = ?", (a,))

    assert enqueue_top_trends(paths, top_n=1) == [b]  # failed `a` is not counted as top-1 candidate
    assert [j["ref_id"] for j in _jobs(paths)] == [b]

    assert enqueue_trend_analysis(paths, a) is True  # explicit retry
    assert _status(paths, a) == "queued"
    assert sorted(j["ref_id"] for j in _jobs(paths, "queued")) == sorted([a, b])
    assert query_one(paths.db_file, "SELECT analysis_error AS e FROM trend_items WHERE id = ?", (a,))["e"] is None


@pytest.mark.local
def test_top_n_zero_and_limit_and_unknown_item(tmp_path: Path) -> None:
    _app, paths = _make_app(tmp_path)
    ids = [_add_item(paths, "youtube", f"y{i}", i) for i in range(1, 5)]
    assert enqueue_top_trends(paths, top_n=0) == []
    assert _jobs(paths) == []
    assert enqueue_top_trends(paths, top_n=1) == [ids[-1]]  # highest score only
    assert len(_jobs(paths)) == 1
    assert enqueue_trend_analysis(paths, 99999) is False

    cfg = load_settings(paths.config_file)
    cfg.trends.auto_analyse_top_n = 2  # default from settings used when top_n is None
    save_settings(paths.config_file, cfg)
    assert enqueue_top_trends(paths) == [ids[-2]]  # ids[-1] already live, top-2 = {-1, -2}


@pytest.mark.local
def test_migration_011_adds_columns_and_backfills_done(tmp_path: Path) -> None:
    old_dir = tmp_path / "mig10"
    old_dir.mkdir()
    for f in sorted(DEFAULT_MIGRATIONS_DIR.glob("*.sql"))[:10]:
        shutil.copy2(f, old_dir / f.name)
    db = tmp_path / "app.db"
    assert migrate(db, migrations_dir=old_dir) == 10
    with get_conn(db) as conn:
        for ext, analysis in (("a", '{"hook": "h"}'), ("b", None), ("c", "")):
            conn.execute(
                "INSERT INTO trend_items (source, external_id, url, published_at, analysis_json) VALUES ('youtube', ?, 'u', '2026-11-01T00:00:00Z', ?)",
                (ext, analysis),
            )
    assert migrate(db) == len(list(DEFAULT_MIGRATIONS_DIR.glob("*.sql")))  # 011 and every later one applied
    cols = {r["name"] for r in query_all(db, "PRAGMA table_info(trend_items)")}
    assert {"analysis_status", "analysis_error"} <= cols
    got = {r["external_id"]: r["analysis_status"] for r in query_all(db, "SELECT external_id, analysis_status FROM trend_items")}
    assert got == {"a": "done", "b": None, "c": None}


@pytest.mark.local
def test_run_analyse_trend_job_missing_item_and_failure_path(tmp_path: Path) -> None:
    _app, paths = _make_app(tmp_path)
    assert "no longer exists" in run_analyse_trend_job(paths, 424242)

    tid = _add_item(paths, "youtube", "fail", 5)
    # Offline setup: reference file + rea cache already on disk (no yt-dlp, no rea-video subprocess),
    # and no AI route configured, so the AI step raises immediately.
    rel = f"reference/ref_{tid}.mp4"
    (paths.media_dir / "reference").mkdir(parents=True, exist_ok=True)
    (paths.media_dir / rel).write_bytes(b"dummy")
    rea = paths.media_dir / f"reference/rea_{tid}"
    (rea / "stems").mkdir(parents=True)
    (rea / "VIDEO.md").write_text("v", encoding="utf-8")
    (rea / "timeline.md").write_text("t", encoding="utf-8")
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "INSERT INTO reference_videos (trend_item_id, path, downloaded_at) VALUES (?, ?, '2026-11-14T10:00:00Z')",
            (tid, rel),
        )
    cfg = load_settings(paths.config_file)
    cfg.ai.routes.vision = []
    cfg.ai.routes.writer = []
    save_settings(paths.config_file, cfg)

    with pytest.raises(AIError):
        run_analyse_trend_job(paths, tid)

    row = query_one(paths.db_file, "SELECT analysis_status AS s, analysis_error AS e, analysis_json AS a FROM trend_items WHERE id = ?", (tid,))
    assert row["s"] == "failed" and row["a"] is None
    assert row["e"] and len(row["e"]) <= 160 and "vision" in row["e"]


class _BatchWriter:
    """Writer provider object: proposes one suggestion per trend item named in the prompt, records each prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema):  # type: ignore[no-untyped-def]
        import json as _json
        import re

        self.prompts.append(prompt)
        block = prompt.split("PHÂN TÍCH XU HƯỚNG:\n", 1)[1].split("\n\nTÓM TẮT KHO SHOT", 1)[0]
        ids = [int(m) for m in re.findall(r'"trend_item_id": (\d+)', block)]
        assert _json.loads(block)  # the trend block is valid JSON data
        return schema.model_validate(
            {"suggestions": [{"trend_item_id": i, "text": f"Ý tưởng {i}", "recommended_shot_ids": []} for i in ids]}
        )


@pytest.mark.local
def test_user_jobs_jump_ahead_of_background_analysis(tmp_path: Path) -> None:
    from videocreator.job_store import claim_next_queued_job
    from videocreator.jobs import PRIORITY_PINNED, enqueue_job

    _app, paths = _make_app(tmp_path)
    for i in range(3):
        enqueue_job(paths.db_file, "analyse_trend", ref_id=100 + i)
    pinned_job = enqueue_job(paths.db_file, "analyse_trend", ref_id=200, priority=PRIORITY_PINNED)
    render_job = enqueue_job(paths.db_file, "render", ref_id=7)
    plan_job = enqueue_job(paths.db_file, "plan", ref_id=8)

    order = [int(claim_next_queued_job(paths.db_file)["id"]) for _ in range(6)]
    assert order[:3] == [render_job, plan_job, pinned_job]  # user jobs first (oldest first), then pinned
    assert order[3:] == sorted(order[3:])  # background analyses keep their order
    assert claim_next_queued_job(paths.db_file) is None


@pytest.mark.local
def test_pasted_link_is_queued_with_pinned_priority(tmp_path: Path) -> None:
    _app, paths = _make_app(tmp_path)
    scanned = _add_item(paths, "youtube", "scan", 5)
    pasted = _add_item(paths, "facebook", "paste", 1)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE trend_items SET metrics_json = '{\"pinned\": 1}' WHERE id = ?", (pasted,))
    enqueue_trend_analysis(paths, scanned)
    enqueue_trend_analysis(paths, pasted)
    prio = {j["ref_id"]: j["priority"] for j in _jobs(paths)}
    assert prio == {scanned: 0, pasted: 5}


@pytest.mark.local
def test_scanned_items_get_suggestions_once_per_batch(tmp_path: Path) -> None:
    from videocreator.trends.links import suggest_after_analysis

    _app, paths = _make_app(tmp_path)
    items = [_add_item(paths, "youtube", f"b{i}", score) for i, score in enumerate((3, 9, 5, 1))]
    enqueue_top_trends(paths, top_n=4)
    writer = _BatchWriter()

    def finish(tid: int, status: str = "done") -> list[int]:
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE jobs SET status = ? WHERE kind = 'analyse_trend' AND ref_id = ?", (status, tid))
        if status == "done":
            _mark_analysed(paths, tid)
        return suggest_after_analysis(paths, tid, pinned=False, writer_provider=writer)

    # Items finish in an order unrelated to their score; suggestions wait for the batch to end
    assert finish(items[0]) == []
    assert finish(items[3]) == []
    assert finish(items[2]) == []
    assert writer.prompts == []
    # The last job of the batch fails, yet it still triggers the single suggestion round
    made = finish(items[1], status="failed")
    assert len(writer.prompts) == 1
    assert len(made) == 3  # daily cap of 3, given to the best-scored analysed items
    got = {r["trend_item_id"] for r in query_all(paths.db_file, "SELECT trend_item_id FROM suggestions")}
    assert got == {items[2], items[0], items[3]}  # scores 5, 3, 1 (item 1 failed, not analysed)


@pytest.mark.local
def test_pasted_link_gets_its_own_suggestion_at_once(tmp_path: Path) -> None:
    from videocreator.trends.links import suggest_after_analysis

    _app, paths = _make_app(tmp_path)
    other = _add_item(paths, "youtube", "busy", 9)
    enqueue_trend_analysis(paths, other)  # a scan batch is still running
    pasted = _add_item(paths, "facebook", "pasted", 1)
    _mark_analysed(paths, pasted)
    _mark_analysed(paths, _add_item(paths, "youtube", "older", 8))
    writer = _BatchWriter()

    made = suggest_after_analysis(paths, pasted, pinned=True, writer_provider=writer)
    assert len(made) == 1
    assert query_one(paths.db_file, "SELECT trend_item_id FROM suggestions")["trend_item_id"] == pasted


@pytest.mark.local
def test_pasted_link_finishing_last_also_closes_the_scan_batch(tmp_path: Path) -> None:
    from videocreator.trends.links import suggest_after_analysis

    _app, paths = _make_app(tmp_path)
    scanned = _add_item(paths, "youtube", "scanned", 9)
    _mark_analysed(paths, scanned)  # its batch job finished while the pasted link was still queued
    pasted = _add_item(paths, "facebook", "pasted-last", 1)
    _mark_analysed(paths, pasted)
    writer = _BatchWriter()

    made = suggest_after_analysis(paths, pasted, pinned=True, writer_provider=writer)
    assert len(made) == 2
    got = {r["trend_item_id"] for r in query_all(paths.db_file, "SELECT trend_item_id FROM suggestions")}
    assert got == {pasted, scanned}


@pytest.mark.local
def test_imported_footage_jobs_jump_the_trend_batch_and_quota_waiters_do_not_hold_suggestions(tmp_path: Path) -> None:
    from videocreator.job_store import claim_next_queued_job
    from videocreator.jobs import enqueue_job
    from videocreator.trends.analyse_queue import other_analysis_jobs_pending

    _app, paths = _make_app(tmp_path)
    for i in range(3):
        enqueue_job(paths.db_file, "analyse_trend", ref_id=300 + i)
    analyse = enqueue_job(paths.db_file, "analyse", ref_id=1)
    describe = enqueue_job(paths.db_file, "describe", ref_id=1)
    assert [int(claim_next_queued_job(paths.db_file)["id"]) for _ in range(2)] == [analyse, describe]

    # A batch job parked for AI quota (can be hours) is not "still to run" for the others
    _a, paths2 = _make_app(tmp_path / "b")
    parked = enqueue_job(paths2.db_file, "analyse_trend", ref_id=400)
    with get_conn(paths2.db_file) as conn:
        conn.execute("UPDATE jobs SET status = 'waiting_quota' WHERE id = ?", (parked,))
    assert other_analysis_jobs_pending(paths2, 401) is False
    enqueue_job(paths2.db_file, "analyse_trend", ref_id=402)
    assert other_analysis_jobs_pending(paths2, 401) is True
