# Scout 01: trend pipeline touchpoints for a new `tiktok` source

Date: 2026-11-14. Read from code, not from docs. Purpose: every place that must change or could break when adding a TikTok trend source.

## Pipeline as it exists

```
watch_items --scan_all()--> adapter.fetch(watch) --> upsert_trend_item() --> trend_items
trend_items --analyse_top_trends()--> fetch_reference_video() (yt-dlp) --> rea-video decompose --> analysis_json
trend_items(analysed) --make_suggestions()--> suggestions --> Telegram topic "Xu hướng" / UI
```

Entry: `run_scan_and_suggest_job` in `src/videocreator/api/routes_trends.py:29`, registered twice in `src/videocreator/app.py:224,228` (job kinds; cron + "Quét ngay").

## Files and what they hard-code

| File | Hard-coded source knowledge | Impact |
|---|---|---|
| `src/videocreator/migrations/002_trends.sql:5` | `watch_items.source CHECK (source IN ('youtube','ig_discovery','ad_library','ig_hashtag'))` | **BLOCKER**: inserting `tiktok` raises IntegrityError. Needs migration 010 that rebuilds `watch_items` (SQLite cannot alter a CHECK). `kind` CHECK already allows `account, hashtag, keyword, page`. `trend_items.source` has no CHECK. |
| `src/videocreator/db.py:43-54` | `migrate()` runs `NNN_*.sql` via `executescript`, sets `PRAGMA user_version`. Latest = `009_r2_staging.sql` | New file must be `010_*.sql`. `executescript` commits implicitly; table rebuild must be written as create-new / copy / drop / rename. No other table has a FK to `watch_items` (checked 001-009), so rebuild is safe. |
| `src/videocreator/trends/scan.py:23-32` | `build_trend_sources` dict of 4 adapters | Add `"tiktok"`. |
| `src/videocreator/trends/scan.py:136-142` | A source is stopped for the rest of the scan only when the error text contains `429`, `613`, `quota`, `giới hạn` | TikTok block/captcha errors must contain one of these words, or each remaining TikTok watch item is retried in the same scan (hammering a blocking host). |
| `src/videocreator/trends/base.py` | `TrendSource` protocol: `name`, `kinds`, `status()`, `fetch(watch)`; `TrendItem` fields | No change. |
| `src/videocreator/trends/rank.py:30,42-48` | `ad_library` special case; everything else uses `likes + 2*comments + views/100` over `max(hours, 24)`; reads `likes/like_count`, `comments/comment_count`, `views/view_count` | Works for TikTok if metrics use keys `views, likes, comments`. Extra keys (`shares`, `duration_s`) are ignored: fine. Ranking is per source, so TikTok's larger view counts do not distort other sources. |
| `src/videocreator/trends/youtube.py` | Pattern to copy: class with `name`, `kinds`, `__init__(paths, secrets_store)`, `status()`, `fetch()`; daily counter stored in `settings` (`yt_quota:<day>`) | Reuse the counter pattern for a TikTok per-day request cap. |
| `src/videocreator/trends/download.py:19-64` | `find_yt_dlp_command()`; `_default_yt_dlp_download(url, dest)` uses `--no-playlist`, 80M cap, 240 s timeout | Generic; a TikTok video URL goes through unchanged. Reuse `find_yt_dlp_command()` for the metadata call (subprocess, pinned version, same as spec "yt-dlp: tiến trình con, phiên bản ghim"). |
| `src/videocreator/trends/analyse.py:190-228` | `analyse_top_trends` iterates `SELECT DISTINCT source FROM trend_items`, top K per source | TikTok picked up automatically. Each new source adds K downloads + K rea-video runs (about 20 min each on CPU) + AI calls: check the daily download cap `trends.download_top_n` (5/day, shared by all sources) and AI budget. |
| `src/videocreator/api/routes_trends.py:79-100` | `/watchlist/add` inserts `source`/`kind` with NO validation against the adapter's `kinds` | Today a bad pair yields a 500 from the CHECK. Add validation (source exists, kind in adapter.kinds) with a 400 and a readable message. |
| `src/videocreator/web/templates/watchlist.html:55-58` | `<option>` list of 4 sources | Add TikTok option + hint on accepted value format. |
| `src/videocreator/web/templates/trends.html:57-61` | `ad_library` special case, else views/likes/comments | Works unchanged for TikTok. Source filter: check how the filter list is built (route line ~130-170) before assuming. |
| `src/videocreator/config.py:134-141` | `TrendsConfig`: `scan_at, ad_library_countries, lookback_days, download_top_n, reference_keep_days` | Add TikTok knobs here (max videos per account, pacing, daily cap). `TikTokConfig` at line 144 is for POSTING (`mode`); do not mix. |
| `src/videocreator/telegram_bot.py:251`, `src/videocreator/tg/handlers.py:209` | Read `trend_items` rows generically for suggestion cards | No source-specific code found; verify the card text does not assume a YouTube URL. |
| `pyproject.toml:23` | `yt-dlp==2026.10.26` pinned; installed version confirmed `2026.10.26` | TikTok extractor breaks often; pin stays, bump is a deliberate step. |

## Naming collisions to avoid

- `posting/` already has a TikTok poster (phase 11), secrets for TikTok OAuth, `[tiktok] mode`, `tests/test_tiktok_live.py` (posting). New module must be `trends/tiktok.py` with class `TikTokTrendSource`; new live test goes in `tests/test_trends_live.py`, not `test_tiktok_live.py`. New config keys go under `[trends]`, not `[tiktok]`.
- Source name string: `tiktok` (matches the platform key used in captions JSON; `trend_items.source` and `posts.platform` are different columns, no clash).

## Spec rules that bind this feature (`docs/video-creator-spec.md`)

- `FR-TRD-02` lists sources in priority order; TikTok is absent, spec needs a line.
- `FR-TRD-03`: one source failing never blocks others; track each source's limit and stop before exceeding.
- `FR-TRD-04`: score within a source only.
- `BR-REF-01..03`: reference files only in `media/reference/`, N per day, deleted after 7 days, never into shots or renders.
- `BR-REF-04`: download without login, cookies, proxy or block evasion; on failure fall back to metrics + caption analysis.
- Assumption 5 (spec line 654): user accepts the grey-area nature of downloading reference videos within `BR-REF-*`.

## Tests that touch this area (must stay green)

`tests/test_rank.py` (score + upsert + watchlist UI + disabled source), `tests/test_suggestion_flow.py`, `tests/test_tg_messages.py`, `tests/test_tg_flows.py`, `tests/test_metrics.py`, `tests/test_db.py` (migration count / user_version: check for a hard-coded `9`), `tests/test_transfer.py` (config export/import: new config keys must round-trip), `tests/test_trends_live.py`.

## Runtime state at scout time

- Server running on `127.0.0.1:8765`; live `app.db` at user_version 9 with 1 watch item, 15 trend items, 5 suggestions. Migration 010 will run against real data on next start: back up `app.db` first (folder `backups/` exists).
- Project rule (CLAUDE.md): no mock/fake data in tests.

## Unresolved

1. Does `tests/test_db.py` assert an exact migration number?
2. How the `/trends` page builds its source filter list (static list or DISTINCT).
