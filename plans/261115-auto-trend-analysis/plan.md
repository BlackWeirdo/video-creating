# Auto trend analysis at scan time

Goal: scanned trend items get AI analysis automatically; UI shows queued/running/failed instead of a bare "Chưa phân tích".

## Findings (code-verified)
- `trends/scan_job.py` (18 lines): scan_all -> analyse_top_trends (serial, top 3/source, failures swallowed) -> make_suggestions.
- `trends/links.py::run_analyse_trend_job` already: skip if analysed, `analyse_trend_item(ignore_download_cap=True)`, then `make_suggestions`. Reuse it; no new job kind.
- `jobs.py`: `QuotaWaitRequested` -> job `waiting_quota`, nothing re-runs it. Other exceptions -> job `failed`. Single-concurrency worker, so N jobs run serially (~1 min each).
- `make_suggestions` caps 3/day and picks only analysed items without a suggestion, so calling it after every analyse job is safe and duplicate-free (cheap early return when nothing to do).
- Latest migration: `migrations/010_watch_items_more_sources.sql` -> new is `011`. ALTER TABLE ADD COLUMN precedent in 008.
- Routes are in `src/videocreator/api/routes_trends.py` (139 lines); template `web/templates/trends.html` (~77-83); config `TrendsConfig` in `config.py` (~85).
- `scan_trends` and `trend_scan` both map to `run_scan_and_suggest_job` (job_handlers.py 39-47).

## Design decisions
- Status columns live on `trend_items` (UI reads them via the existing query, no join).
- Quota wait: item -> `failed` with message "Hết quota AI, bấm Phân tích lại sau"; re-raise so job still shows waiting_quota. No auto-resumer (nothing resumes waiting_quota jobs today; YAGNI).
- BudgetExceeded -> `failed`, message "Hết ngân sách AI hôm nay"; job returns normally.
- Other errors -> `failed`, `analysis_error` = short text (`str(exc)[:160]`), never stderr/traceback (detail stays in job log_tail); re-raise so the job is `failed` too.
- Download cap: scan-time analyse respects the daily cap (falls back to caption+metrics path, already works); pinned/pasted items keep `ignore_download_cap=True`. Decide inside handler via `metrics_json.pinned`.
- Re-scan idempotent: top-N skips items with status queued/running/failed or analysed. Failed items are retried by hand only (no quota burn each scan).
- Stuck status guard: treat `queued/running` as in-flight only if a matching jobs row (kind=analyse_trend, ref_id, status queued/running) exists; otherwise re-enqueue (small EXISTS in SQL).

## Steps (each one conventional commit)

### 1. Migration + config  `feat(db): add trend analysis status columns`
- NEW `src/videocreator/migrations/011_trend_analysis_status.sql`: ADD COLUMN `analysis_status TEXT`, `analysis_error TEXT` (nullable, no CHECK). One UPDATE backfill: rows with analysis_json set -> `done`.
- `config.py` `TrendsConfig`: `auto_analyse_top_n: int = 10` (ge=0; 0 disables).
- Grep tests for `get_user_version` assertions (test_trends_facebook_links.py) and bump expected version.

### 2. Queue helpers + scan job  `feat(trends): queue analysis jobs per scanned item`
- NEW `src/videocreator/trends/analyse_queue.py` (<100 lines):
  - `set_analysis_status(db, id, status, error=None)`.
  - `enqueue_trend_analysis(paths, id) -> bool`: if analysis_json empty and not in-flight (see guard): status `queued`, error NULL, `enqueue_job(db, "analyse_trend", ref_id=id)`. Single transaction check-then-set. Allows `failed` (used by retry route).
  - `enqueue_top_trends(paths, top_n=None) -> list[int]`: per source, analysis_json NULL/empty, status not in (queued, running, failed) or stale, `ORDER BY score DESC, id ASC LIMIT top_n` (default `trends.auto_analyse_top_n`).
- `trends/scan_job.py`: scan_all -> `enqueue_top_trends` -> `make_suggestions` (still runs for items analysed earlier without a suggestion); result string reports `queued=N`.
- `trends/analyse.py`: delete `analyse_top_trends` (unused afterwards); grep callers incl. `tests/test_trends_live.py` and fix.
- `trends/links.py::add_pasted_link`: call `enqueue_trend_analysis` instead of raw `enqueue_job` so status becomes queued. Keep imports lazy to avoid a links <-> analyse_queue cycle (or define the job-kind constant in analyse_queue and import it in links/job_handlers).

### 3. Handler status tracking  `feat(trends): track analysis status in job`
- `links.py::run_analyse_trend_job` (or move into analyse_queue.py if links nears 200 lines; now 130):
  - start: status `running`.
  - success: `done`, error NULL, then `make_suggestions` in its own try (a suggestion failure must not mark the analysis failed; log warning).
  - `QuotaWaitRequested`: `failed` + quota message, re-raise. `BudgetExceeded`: `failed` + budget message, return string. Other Exception: `failed` + short error, re-raise.
  - missing item / already analysed: unchanged early returns (set `done` if analysed).

### 4. Routes  `feat(trends): analyse on upload and retry route`
- `api/routes_trends.py` `upload_reference_video_route`: after DB write call `enqueue_trend_analysis` (no-op if already analysed).
- NEW `POST /trends/{item_id}/analyse`: 404 if missing; calls `enqueue_trend_analysis`; redirect `/trends?msg=analysis_queued` (or `already_queued`). Add msg text wherever `reference_uploaded` is rendered.

### 5. UI  `feat(ui): show trend analysis status`
- `trends.html` analysis cell: analysis present -> as today; status queued -> `Đang chờ phân tích`; running -> `Đang phân tích...`; failed -> `Lỗi: {{ analysis_error }}` + form POST `/trends/{id}/analyse` button `Phân tích lại`; else `Chưa phân tích` + same retry button (covers old rows beyond top N). Row dicts already use `**r`, so no route change. No polling (YAGNI).

### 6. Tests  `test: cover auto analysis queueing`
Real sqlite (tmp_path + `migrate`), real `jobs` table, real `TestClient(create_app)`, no mocks. NEW `tests/test_trends_auto_analysis.py` (<200 lines):
- Migration 011 adds columns; backfill marks analysed rows `done`.
- `enqueue_top_trends`: 12 items one source, top_n=10 -> exactly 10 `analyse_trend` jobs queued, best scores first, rows `queued`; 2nd call -> 0 (idempotent); analysed and failed rows skipped; per-source limit across 2 sources; top_n=0 -> none; stale `queued` row with no job row is re-enqueued.
- `make_suggestions` early return with no analysed items (no AI touched).
- Handler without AI: missing id and already-analysed paths. A true failure path only if `get_provider` with empty secrets raises deterministically (verify in `ai/router`); else leave to live test.
- Routes: POST `/trends/{id}/analyse` on failed row -> queued + exactly one job, repeat -> no duplicate, unknown id -> 404; upload-reference on unanalysed item enqueues once, on analysed item none; GET `/trends` HTML contains `Đang chờ phân tích`, `Lỗi:` + `Phân tích lại`, `Chưa phân tích` for the matching rows.
- Do NOT call `run_scan_and_suggest_job` (network). The real AI call is covered by one new `-m live` test: queue 1 item, `run_one_job`, assert status `done` and analysis_json set.
- Update tests referencing `analyse_top_trends` and the migration version; run `pytest -m "not live"`.

## Risks
- Load: up to 10 x 5 sources = 50 AI calls per scan, ~1 min each serial on the single worker; render/studio jobs queue behind them. Consider lower default (5) or tell user.
- Quota/budget exhausted mid-queue: remaining jobs fail fast with message; user retries manually; possible burst of `waiting_quota` jobs.
- Stale status after crash/lost job: handled by the EXISTS guard.
- Download cap (5/day) means most scan items use caption+metrics only (lower quality; unchanged behaviour).
- Import cycle links <-> analyse_queue.
- Deleting `analyse_top_trends` may break live tests/other callers; grep first.
- Existing ~100 old unanalysed rows have NULL status; first scan queues top N of them (desired).

## Unresolved questions
1. Reference video uploaded for an item already analysed from text: re-analyse with the video? (plan: no).
2. Default `auto_analyse_top_n` 10 vs lower, given ~50 min serial backlog?
3. Auto-retry failed items on next scan, or manual only? (plan: manual only).
4. Should scan-time analysis bypass the download cap? (plan: no).
5. Need auto-refresh of /trends while items run?
6. Quota-wait items shown as failed w/ message acceptable, or build resume for waiting_quota jobs (out of scope)?
