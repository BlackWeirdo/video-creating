# Scout 01: code locations for the 10 review findings (2026-11-15)

Source: full read of core, ai/, pipeline/, posting/, trends/, tg/, studio/ in this session. Paths relative to `src/videocreator/`. Baseline: 158 non-live tests pass (`.venv/Scripts/python.exe -m pytest -m "not live"`, ~4 min). Working tree has UNCOMMITTED work (auto trend analysis, refactor); do not revert it.

## F1. Trend analysis never reaches the script writer
- `trends/suggest.py:151-155` stores `formula_json = {formula, recommended_shot_ids, missing_shots}` only. `trend_items.analysis_json` (hook, structure[], cut_pace_s, text_style, music_mood, why_it_works; schema `trends/analyse.py:17-28`) is dropped.
- `trends/suggestion_actions.py:57-71` passes `formula_obj` to `save_plan_request_params`; `pipeline/plan_prompts.py:93-96` dumps it as "CÔNG THỨC XU HƯỚNG".
- `pipeline/replan.py:33-40` re-reads `suggestions.formula_json` for redo (same gap).
- `recommended_shot_ids` is never used by the planner beyond being shown in JSON text.

## F2. Auto quality score blind with Claude
- `pipeline/quality_score.py:67-71` calls `vis.describe_video(video_file, prompt, VideoQualityScore)` with NO thumbnails.
- `ai/claude_cli.py:20-32` `_stage_thumbnails`: no thumbs -> one middle frame. `ai/claude.py:141-146` same.
- `ai/gemini.py:109-141` uploads the whole video (fine).
- Score < `quality.min_score` (8) -> `redo.redo_video(..., is_auto_retry=True)` up to 2x -> new plan + render (`quality_score.py:95-105`). Plan JSON truncated to 1200 chars in prompt.
- Frame extraction helper: `pipeline/thumbs.py extract_thumbnail(video, t, dest)`. FFmpeg whitelist `pipeline/ffmpeg.py:13-36` (no `select`, `tile`, `drawtext`).
- Gemini only used when routed; current uncommitted default routes `vision=["claude_api"]` (`config_ai.py:10-12`).

## F3. Single-worker queue, no priority; trend analysis floods it
- `jobs` table (`migrations/001_core.sql:120-130`): no priority column. `job_store.claim_next_queued_job` (`job_store.py:88-115`) `ORDER BY id ASC`.
- `trends/analyse_queue.enqueue_top_trends` (`analyse_queue.py:43-63`): `trends.auto_analyse_top_n` default 10 per source (`config.py:94`). rea-video timeout 1800s (`trends/rea_reference.py:15`).
- `trends/links.run_analyse_trend_job` (`links.py:145`) calls `make_suggestions` after EACH item -> 3/day quota (`suggest.py:102-107`) consumed by first finished items, not best.
- `scan_job.py` calls `make_suggestions` right after queueing (usually nothing analysed yet).
- User-facing kinds needing priority: `plan` (Telegram create), `render`, `replan`, `studio`. Background: `analyse_trend`, `scan_trends`/`trend_scan`, `describe`, `broll_suggest`, `analyse`.
- Migrations numbered; next free = `012_*.sql`. `db.migrate` applies by sorted filename index.

## F4. Library planning sends whole shot library
- `pipeline/plan_store.load_source_shots` (`plan_store.py:13-30`): library mode = `SELECT * FROM shots ORDER BY quality DESC` (all, incl. undescribed `description=''`).
- `pipeline/plan_prompts.build_planner_prompt` (`plan_prompts.py:58-116`): no rule about one product per video / collection formula; validator `plan_validate._check_products_not_mixed` (`plan_validate.py:92-103`) rejects mixed non-collection plans afterwards.
- Library mode used by suggestions (`ref_id = -suggestion_id`, `plan_request.py:62`) and `/create`.

## F5. Original footage audio always dropped
- `pipeline/render_steps.cut_shot_segments` uses `-an` (`render_steps.py:92`); `export.normalize_to_master` (`export.py:47-90`) mixes voice/music/silence; `elif info.has_audio` branch never hit for cut.mp4.
- `concat_segments` uses `-c copy` -> segments must all have or all lack audio (shots without audio need `anullsrc` pad).
- Allowed filters already include `amix`, `volume`, `afade`, `atrim`, `anullsrc`, `loudnorm`, `aresample`.
- No per-video/per-footage option exists; videos table columns listed in spec §5.

## F6. Facebook posts as plain video; retry can duplicate
- `posting/facebook.py:44-75`: `POST /{page_id}/videos` with `file_url`, 120s timeout; `httpx.RequestError` -> `TransientPostError` -> retried by `publish_outcomes.handle_transient_failure` -> second POST = duplicate.
- Instagram/Threads already persist `posts.remote_container_id` before publish (`instagram.py:79-102`, `threads.py:54-74`) — reuse that column for FB reel `video_id`.
- `job_store.recover_interrupted_jobs` (`job_store.py:32-38`) resets `publishing` only when no container id (posts with id stay stuck — spec §6 says query platform).
- Graph helper `posting/meta_auth.py` (`GRAPH_BASE_URL`, `classify_meta_error`), `posting/instagram_graph.graph_request`.
- Live test file: `tests/test_meta_live.py` (skipped without token).

## F7. Failed metric fetch recorded as empty row forever
- Readers return `empty_metrics()` (all None) on any error (`facebook.py:80-103`, `instagram.py:130-153`, `tiktok.py:182-185`).
- `posting/metrics.collect_due_metrics` (`metrics.py:167-185`) inserts row even when all None; `UNIQUE(post_id, checkpoint)` + `INSERT OR IGNORE` -> never retried. Window `MAX_COLLECTION_WINDOW_HOURS = 24` (`metrics.py:37`).
- Report treats `views IS NULL` as "không có dữ liệu" (`reports.py:137`) — correct for platforms with no data (TikTok), wrong for transient failures.

## F8. Footage import copies file while holding DB write lock
- `pipeline/footage_import.import_footage_file` (`footage_import.py:77-114`): INSERT, then `shutil.copy2` (GBs) inside `with get_conn(...)`, then UPDATE path. busy_timeout 5s (`db.py:21`) -> other writers fail "database is locked".
- sha256 dedupe has UNIQUE in schema (spec §5) — race between check and insert handled by constraint.

## F9. Budget guard gaps
- `ai/budget.estimate_token_cost` (`budget.py:16-30`) returns 0.0 when model missing from `[prices]` -> unlimited spend unnoticed. Current gateway models: `claude-opus-5-5`, `claude-haiku-5-5` priced; `gemini-3.6-flash` NOT in `_default_prices` (`config_ai.py:59-66`), only in user's config.toml.
- `today_utc_str()` (`budget.py:12-13`) -> day resets 07:00 VN. Same in `reports.daily_summary` (`reports.py:68`, uses `base_utc` day for AI stats) and `trends/links._today_key` (`links.py:37-38`), `download.count_today_reference_downloads` (`download.py:69-79`), `suggest.py:103` (`strftime('%Y-%m-%dT00:00:00Z','now')`).
- `ai_usage.day` column stores the string; changing day basis affects historic rows only cosmetically.
- `schedule.timezone` in config (`config.py:28`) is the natural local day source; `timeutil.py` has helpers.

## F10. TikTok inbox message lacks caption
- `posting/publish_outcomes.notify_published` (`publish_outcomes.py:74-90`) needs_user_action text has no caption. Caption available via `posting/captions.format_platform_caption(video_row, "tiktok")`. Telegram text limit 4096 (sender truncates).
- `posting/tiktok._publish_inbox` sends no caption (API inbox init has no post_info).

## Test conventions
- No mocks (CLAUDE.md): tests use real SQLite tmp dirs, real FFmpeg on `tests/samples/`, provider overrides via injected objects that run real code paths; live tests marked `live` and skip without keys.
- Existing relevant tests: `test_render.py`, `test_posting_service.py`, `test_metrics.py`, `test_jobs.py`, `test_budget.py`, `test_suggestion_flow.py`, `test_tg_messages.py`, `test_trend_auto_analysis.py`.

## Unresolved
- Whether owner wants Gemini (paid, sees video) or Claude frames (subscription) for scoring — depends on open routing decision (review item 1.1).
- Whether to keep original audio by default or per footage.
