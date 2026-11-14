# Report 01: real-run spike, yt-dlp against TikTok (2026-11-14)

Run on the server PC (Windows, residential IP, Vietnam), venv `yt-dlp==2026.10.26`, no cookies, no login, no proxy, `curl_cffi` NOT installed.

## Results

| Test | Command | Result |
|---|---|---|
| Account listing, metadata only | `python -m yt_dlp --flat-playlist --playlist-end 3 -J --no-warnings https://www.tiktok.com/@tiffanyandco` | **PASS**, exit 0, a few seconds. Extractor `tiktok:user`. |
| Hashtag listing | same flags, `https://www.tiktok.com/tag/silverjewelry` | **FAIL**, exit 1, `ERROR: No working app info is available`, `entries: [null]` |
| Extractor list | `--list-extractors` | `TikTok`, `tiktok:collection`, `tiktok:live`, `tiktok:user`, `vm.tiktok` working; `tiktok:tag`, `tiktok:sound`, `tiktok:effect` marked `(CURRENTLY BROKEN)`. No search extractor. |

## Fields in a flat entry (real output, sample saved as `spike-tiktok-user-flat-sample.json`)

Playlist level: `id` (secUid), `title` (handle), `extractor = "tiktok:user"`, `entries[]`.
Entry level: `id` (video id), `url` (`https://www.tiktok.com/@<handle>/video/<id>`), `uploader` (handle), `channel` (display name), `title`, `description`, `timestamp` (epoch s, UTC), `duration` (s), `view_count`, `like_count`, `comment_count`, `repost_count`, `save_count`, `track`, `artists`.

Mapping to `TrendItem`: `external_id = id`, `url = url`, `author = channel or uploader`, `caption = description or title`, `published_at = fromtimestamp(timestamp, UTC)`, `metrics = {views, likes, comments, shares: repost_count, saves: save_count, duration_s}`.

## Conclusions

1. Account watch works today with one request per account and gives every metric the existing score formula needs. No per-video request needed at scan time.
2. Hashtag and keyword scanning are NOT possible with this tool without a logged-in session. Do not build them.
3. Console output showed mojibake for non-ASCII captions: subprocess must be read as UTF-8 (`encoding="utf-8", errors="replace"`, as `download.py` already does), never the Windows default code page.
4. `curl_cffi` was not needed. Do not add the dependency.

## Not tested (left for implementation phase)

- Downloading one TikTok video file with the existing `_default_yt_dlp_download` (single-video extractor is listed as working).
- Behaviour after many consecutive listings (block / captcha wording), so the error text to match is not yet known.
- Private, empty, renamed or non-existent account.
