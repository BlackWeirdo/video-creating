# yt-dlp TikTok extraction for metadata-only trend scanning (state: Nov 2026)

Scope: yt-dlp only. Source read = `yt_dlp/extractor/tiktok.py` on master via raw GitHub (summarized by fetch tool, not line-verified). Web search gave issue-level signals, not a status table. Confidence flags in [brackets].

## 1. Extractors and status

| Extractor (IE_NAME) | URL form | Type | Status per source |
|---|---|---|---|
| TikTokIE (`tiktok`) | `tiktok.com/@u/video/ID`, `tiktokv.com` | single video | Active. Web path gets audio only at 1080p (FIXME in source) |
| TikTokUserIE (`tiktok:user`) | `tiktok.com/@name` or `tiktokuser:<secUid>` | playlist, flat | Active |
| TikTokCollectionIE (`tiktok:collection`) | `@u/collection/title-ID` | playlist, flat | Active, web endpoint, no app_info/impersonation |
| TikTokTagIE (`tiktok:tag`) | `/tag/NAME` | playlist, full | `_WORKING = False` [verify in source] |
| TikTokSoundIE (`tiktok:sound`) | `/music/...-ID` | playlist, full | `_WORKING = False` [verify] |
| TikTokEffectIE (`tiktok:effect`) | `/sticker/...-ID` | playlist, full | `_WORKING = False` [verify] |
| TikTokLiveIE (`tiktok:live`) | `@u/live` | single live | Active, needs impersonation to resolve room ID |
| TikTokVMIE (`vm.tiktok`) | `vm.`/`vt.` short links | redirect | Active |
| DouyinIE | douyin.com | single | Needs `s_v_web_id` cookie. Not relevant |

Implications:
- Hashtag (`tiktok:tag`) and sound extractors are flagged non-working in source. Hashtag scanning via yt-dlp is not a reliable path.
- Keyword search: no TikTok search extractor in the list above. Not supported.
- No cookies needed for user, collection, single video, live (per source). Login redirect on single video raises login-required error, so breakage is possible.

## 2. User profile listing (`tiktok:user`)

Recommended command (metadata only, no media):
```
yt-dlp --flat-playlist --playlist-end 20 --skip-download -J "https://www.tiktok.com/@HANDLE"
```
- `-J` dumps one JSON with `entries`. Use `--dump-single-json`/`-J` for playlist, `--dump-json` gives one JSON per line (per-entry).
- `--flat-playlist` = `extract_flat` = entries are URL stubs with partial metadata. Full metadata needs a second `extract_info(url, download=False)` per video.
- Source: page size `count=15`, cursor = last item `createTime` (ms). Stops when cursor < 1472706000000 or `hasMorePrevious` false. So `--playlist-end` is the real cap; paging is done internally.
- Source comment: "User may not have posted within this ~1 week lookback". Inactive accounts may return 0 entries. Not an error.

Fields:
- Flat entries (user/collection): `id`, `title`, `description`, `duration`, `timestamp`, `view_count`, `like_count`, `repost_count`, `comment_count`, `save_count`, `uploader`, `uploader_id`, `uploader_url`, `channel`, `channel_id`, `track`, `album`, `artists`, `thumbnails`. `formats`/`subtitles` = None. Entry URL = video page URL.
- Full entries (add `formats`, `subtitles`, `availability`, `webpage_url`). Full extraction is per video, slower, more request load.
- Not `artist` (singular). Parser emits `artists` (list). Test dicts use `artist`; do not rely on it.
- Live: no description, duration, timestamp, counts.

`secUid`:
- Source accepts `tiktokuser:<secUid>` directly (secUid-shaped ID, `MS4wLjABAAAA` + 64 chars) and skips webpage lookup.
- If `@handle` fails, source falls back to embed page to find `secUid`. So `tiktokuser:` is a fallback, not required.
- [Unverified] whether the handle fallback fails often in 2026. Source comments do not say.

## 3. Failure modes

Source and search signals (no concrete rates found):
- Rehydration error: "unable to extract universal data for rehydration" (yt-dlp #16199, labeled cant-reproduce). Web page JSON changes break parsing.
- Playlist tracebacks in same extractor path (#15506).
- Fix 2026.03.13: "tiktok: Fix challenge solving" (#16223). Master notes list TikTok fixes #17452, #17460. [Stable release containing these unconfirmed]
- Source uses `impersonate=True` (curl_cffi) on user page, TikTokIE webpage, live. Without curl_cffi installed, expect failures. Install: `pip install yt-dlp[default,curl-cffi]`. [Ensure the Windows build of curl_cffi is in uv.lock]
- JS challenge solving when rehydration data missing (TikTokIE webpage). Needs challenge solver deps; breaks often.
- `app_info` / `device_id`: TikTokIE uses `app_info` to try app API first. TikTokUserIE reads `device_id`. Source comment: bad `device_id` causes infinite loop, now raises (#14031). Do not pass a stale `device_id`. Fetch summary says user extractor does not read `app_info`. [verify]
- Region/IP block, captcha, 403 wave: VideoProc guide reports a general yt-dlp 403 wave from 2026-08-17, not TikTok-specific. Residential IP reduces but does not remove risk. No TikTok-specific captcha reports found.
- "Unable to extract secondary user ID" error: not found in source summary. Treat `secUid` fallback as the workaround if seen.
- Breakage frequency: TikTok changes web/app APIs often. Expect yt-dlp breakage every few weeks to months. Pin yt-dlp, test weekly, update on break.

Pacing (no official number found; recommendations, not sourced):
- Use `--sleep-requests 2-4` (per HTTP request) and `--sleep-interval 5 --max-sleep-interval 15` between videos if fetching full metadata.
- Keep scan to a few accounts, once or twice a day. Random jitter. Stop on first HTTP 403/429.

## 4. Python API pattern

```python
import yt_dlp

opts = {
    "skip_download": True,
    "extract_flat": "in_playlist",   # or True (flat everything); "in_playlist" keeps single-video full
    "playlistend": 20,
    "ignoreerrors": True,            # per-entry errors -> None instead of raise
    "quiet": True,
    "no_warnings": True,
    "sleep_interval_requests": 2,
    "sleep_interval": 5,
    "max_sleep_interval": 15,
    "impersonate": ... ,             # only if your yt-dlp build needs it; check docs
}
with yt_dlp.YoutubeDL(opts) as ydl:
    info = ydl.extract_info("https://www.tiktok.com/@HANDLE", download=False)
    for e in info.get("entries") or []:
        if e is None:       # failed entry under ignoreerrors
            continue
        ...
```
- `extract_flat` values: `False`, `True`, `"in_playlist"` (per yt-dlp docs). Confirm in `YoutubeDL` docs before use.
- `ignoreerrors=True` skips per-entry failures. Still wrap the call in try/except for user-level failures (login-required, not-found, UserNotLive).
- To get full counts for flat entries, call `extract_info(entry["url"], download=False)` per video, with sleep between calls.
- `impersonate` option: check current docs for the key name and `ImpersonateTarget`. Not verified here.

## 5. No-auth hashtag / keyword scan

Honest answer: no reliable no-auth path in yt-dlp in late 2026.
- Hashtag extractor marked non-working in source.
- No keyword search extractor.
- Alternatives (not verified here, each has its own issues): TikTok Research API (official, needs approved app, eligibility limited to researchers/US-based orgs as of last known terms), TikTok Commercial Content API, third-party scrapers (ToS and reliability risk). Check TikTok developer portal before choosing.
- Practical workaround: keep scanning by creator account (`tiktok:user`) and build the hashtag list from known creators.

## 6. ToS and practical risk

- TikTok Terms of Service prohibit automated access/scraping without permission [from knowledge, not verified in this session; check https://www.tiktok.com/legal/page/row/terms-of-service/en]. Metadata collection of public content is still "automated access" under most readings.
- Practical risk for low volume (a few accounts, 1-2 runs/day, one residential IP): low probability of account action, since no login is used. Risks: IP-level throttling/captcha, yt-dlp breakage, and legal/ToS exposure if output is redistributed.
- Mitigation: no login, low rate, jitter, stop on 403/429, store only metadata, internal use only, prefer official API when scale grows.

## Sources

- yt-dlp TikTok extractor source: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/tiktok.py (raw: https://raw.githubusercontent.com/yt-dlp/yt-dlp/master/yt_dlp/extractor/tiktok.py)
- yt-dlp issue #16199 (rehydration): https://github.com/yt-dlp/yt-dlp/issues/16199
- yt-dlp issue #15506 (playlist tracebacks): https://github.com/yt-dlp/yt-dlp/issues/15506
- yt-dlp releases (2026.03.13 TikTok challenge fix): https://github.com/yt-dlp/yt-dlp/releases
- yt-dlp master builds (#17452, #17460): https://github.com/yt-dlp/yt-dlp-master-builds/releases
- yt-dlp issue #9506 (older feed parsing, likely outdated): https://redirect.github.com/yt-dlp/yt-dlp/issues/9506
- Community TikTok extractor fork: https://github.com/bashonly/yt-dlp-TTUser
- 403 wave guide (not TikTok-specific): https://www.videoproc.com/resource/yt-dlp-not-working.htm
- TikTok Terms of Service: https://www.tiktok.com/legal/page/row/terms-of-service/en (not fetched this session)

## Unresolved questions

1. Confirm `_WORKING = False` for TikTokTagIE/SoundIE/EffectIE on current master (fetch summary only; check file directly).
2. Does TikTokUserIE read `app_info` or only `device_id`? Source summary conflicts with TikTokIE behavior.
3. Exact pacing that avoids TikTok throttling/captcha for a single residential IP: no source data. Needs a timed test.
4. Is `curl_cffi` (impersonation) required on Windows for user listing in the pinned yt-dlp version? Check `uv.lock`.
5. Does the `tiktokuser:<secUid>` fallback work for accounts where the `@handle` lookup fails? Need a live test.
6. Which stable yt-dlp release includes master fixes #17452/#17460?
7. Exact current TikTok ToS wording on automated access (not fetched).
8. Eligibility/cost for TikTok Research API or Commercial Content API, if scale grows.
9. Real failure rate: no quantitative data found. Plan a 2-week canary run to measure.
