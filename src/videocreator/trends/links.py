"""Pasted Facebook / Instagram video links as trend items (web form and Telegram `/link`).

The owner finds a good Reel by hand (Facebook Reels feed, a Page, a Profile) and pastes the
link. The app reads that one public video's metadata with the pinned yt-dlp (no login, no
cookies, `BR-REF-04`), stores it as a trend item flagged `pinned`, and queues `analyse_trend`
so it is downloaded, analysed with rea-video and offered for suggestions ahead of scanned items.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from videocreator.db import get_conn, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.trends.base import TrendItem
from videocreator.trends.download import find_yt_dlp_command
from videocreator.trends.facebook import FACEBOOK_HOSTS
from videocreator.trends.scan import upsert_trend_item

logger = logging.getLogger("videocreator.trends.links")

ANALYSE_TREND_JOB_KIND = "analyse_trend"
MAX_PASTED_LINKS_PER_DAY = 20
YTDLP_TIMEOUT_S = 90

INSTAGRAM_HOSTS = frozenset({"instagram.com", "www.instagram.com"})
FB_WATCH_HOSTS = frozenset({"fb.watch", "www.fb.watch"})

# Paths that point at ONE video. Page/Profile links are refused here and belong in the Watchlist.
_FB_VIDEO_PATH = re.compile(
    r"^/(?:reel/\d+|watch/?|video\.php|share/[rv]/[A-Za-z0-9]+|[A-Za-z0-9.\-]+/videos/(?:[^/]+/)?\d+)/?$",
    re.ASCII,
)
_IG_VIDEO_PATH = re.compile(r"^/(?:[A-Za-z0-9._]+/)?(?:reel|reels|p|tv)/[A-Za-z0-9_-]+/?$", re.ASCII)
_URL_IN_TEXT = re.compile(r"https://\S+")
# "9.9K views · 340 reactions | ..." (English) or "9,9K lượt xem · 340 cảm xúc | ..." (Vietnamese).
_COUNT_IN_TITLE = re.compile(
    r"(\d[\d.,]*)\s*(K|M|B|Tr)?\s*(views|lượt xem|reactions|(?:lượt\s+)?cảm xúc|comments|(?:lượt\s+)?bình luận|shares|lượt chia sẻ)",
    re.IGNORECASE,
)
_TITLE_COUNTS_PREFIX = re.compile(r"^[^|]*(?:views|lượt xem|reactions|cảm xúc)[^|]*\|\s*", re.IGNORECASE)

PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram"}


def extract_first_url(text: str) -> str:
    """Returns the first https link in a message (Telegram shares put text before the link)."""
    m = _URL_IN_TEXT.search(text or "")
    return m.group(0).rstrip(").,;!?\"'") if m else ""


def classify_video_url(url: str) -> tuple[str, str]:
    """Returns `(platform, cleaned_url)` for a single Facebook/Instagram video link.

    Raises `ValueError` (Vietnamese) for anything else, before any network call.
    """
    raw = (url or "").strip()
    if raw.startswith("-"):
        raise ValueError("Link không hợp lệ.")
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise ValueError("Chỉ nhận link https của Facebook hoặc Instagram.")
    path = parts.path or "/"

    if host in FB_WATCH_HOSTS and len(path.strip("/")) > 0:
        return "facebook", urlunsplit(("https", host, path, "", ""))
    if host in FACEBOOK_HOSTS:
        if not _FB_VIDEO_PATH.match(path):
            raise ValueError(
                "Đây không phải link một video/Reel Facebook. Link Fanpage hoặc Profile hãy thêm ở trang Watchlist."
            )
        query = ""
        if path.rstrip("/") in ("/watch", "/video.php"):
            vid = (parse_qs(parts.query).get("v") or [""])[0]
            if not (vid.isascii() and vid.isdigit()):
                raise ValueError("Link watch của Facebook thiếu mã video (v=...).")
            query = f"v={vid}"
        return "facebook", urlunsplit(("https", "www.facebook.com", path, query, ""))
    if host in INSTAGRAM_HOSTS:
        if not _IG_VIDEO_PATH.match(path):
            raise ValueError("Đây không phải link một bài/Reel Instagram.")
        return "instagram", urlunsplit(("https", "www.instagram.com", path, "", ""))
    raise ValueError("Chỉ nhận link video Facebook hoặc Instagram.")


def _parse_count(number: str, suffix: str) -> int:
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "tr": 1_000_000}.get((suffix or "").lower(), 1)
    if mult > 1:
        return round(float(number.replace(",", ".")) * mult)
    return int(re.sub(r"[.,]", "", number) or 0)


def counts_from_title(title: str) -> dict[str, int]:
    """Reads the counts Facebook puts in a Reel's page title ("9.9K views · 340 reactions | ...")."""
    found: dict[str, int] = {}
    for number, suffix, word in _COUNT_IN_TITLE.findall(title or ""):
        w = re.sub(r"^lượt\s+(?=cảm|bình)", "", word.lower())
        key = (
            "views" if w in ("views", "lượt xem")
            else "likes" if w in ("reactions", "cảm xúc")
            else "comments" if w in ("comments", "bình luận")
            else "shares"
        )
        try:
            found.setdefault(key, _parse_count(number, suffix))
        except ValueError:
            continue
    return found


def _first_video_entry(data: dict[str, Any]) -> dict[str, Any]:
    """Instagram posts with several media come back as a playlist: use the first video in it."""
    def is_video(d: dict[str, Any]) -> bool:
        return bool(d.get("duration")) or d.get("vcodec") not in (None, "none")

    if data.get("_type") != "playlist":
        if not is_video(data):
            raise ValueError("Bài này không có video.")
        return data
    for entry in data.get("entries") or []:
        if entry and is_video(entry):
            merged = {**data, **{k: v for k, v in entry.items() if v is not None}}
            merged["id"] = data.get("id") or entry.get("id")  # the post: that is what gets downloaded
            return merged
    raise ValueError("Bài này không có video.")


def parse_single_video(data: dict[str, Any], *, platform: str, url: str, now_dt: datetime | None = None) -> TrendItem:
    """Maps one yt-dlp `-J` result to a pinned `TrendItem`."""
    d = _first_video_entry(data)
    video_id = str(d.get("id") or "").strip()
    if not video_id:
        raise ValueError("Không đọc được mã video.")

    title = str(d.get("title") or "")
    title_counts = counts_from_title(title) if platform == "facebook" else {}
    views = max(int(d.get("view_count") or 0), title_counts.get("views", 0))
    likes = int(d.get("like_count") or 0) or title_counts.get("likes", 0)
    comments = int(d.get("comment_count") or 0) or title_counts.get("comments", 0)
    shares = int(d.get("repost_count") or 0) or title_counts.get("shares", 0)

    metrics: dict[str, Any] = {
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "duration_s": round(float(d.get("duration") or 0.0), 2),
        "pinned": True,
    }
    ts = d.get("timestamp")
    if ts:
        published = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    else:
        published = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
        metrics["date_unknown"] = True

    caption = str(d.get("description") or "").strip() or _TITLE_COUNTS_PREFIX.sub("", title).strip()
    return TrendItem(
        source=platform,
        external_id=video_id,
        url=url,
        author=str(d.get("channel") or d.get("uploader") or d.get("uploader_id") or ""),
        caption=caption[:1000],
        published_at=published,
        metrics=metrics,
        video_url=url,
    )


def _pasted_count_key(day: str) -> str:
    return f"pasted_links:{day}"


def _today_key(now_dt: datetime | None) -> str:
    return _pasted_count_key((now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d"))


def _check_daily_cap(db_file: Path, *, now_dt: datetime | None = None) -> None:
    row = query_one(db_file, "SELECT value FROM settings WHERE key = ?", (_today_key(now_dt),))
    used = int(row["value"]) if row and str(row["value"]).isdigit() else 0
    if used >= MAX_PASTED_LINKS_PER_DAY:
        raise ValueError(f"Đã đủ {MAX_PASTED_LINKS_PER_DAY} link hôm nay. Hãy thử lại vào ngày mai.")


def _count_link(db_file: Path, *, now_dt: datetime | None = None) -> None:
    """Counts one successfully read link (failed reads and typos do not use the day's slots)."""
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, '1')
            ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            """,
            (_today_key(now_dt),),
        )


def read_video_metadata(url: str) -> dict[str, Any]:
    """Runs the pinned yt-dlp for ONE public video, metadata only. Messages never embed stderr."""
    # --ignore-config: a user-level yt-dlp.conf (cookies...) must never apply (BR-REF-04).
    cmd = [*find_yt_dlp_command(), "--ignore-config", "--skip-download", "--no-playlist", "-J", "--no-warnings", "--", url]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=YTDLP_TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Nền tảng không trả lời kịp. Hãy thử lại sau.") from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        logger.info("yt-dlp could not read %s: %s", url, proc.stderr[-500:])
        raise ValueError(
            "Không đọc được video này khi không đăng nhập (video riêng tư, đã xoá, hoặc nền tảng chặn). "
            "Hãy tải file về rồi bấm 'Nạp video tham khảo' ở bài tương ứng."
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("yt-dlp trả về dữ liệu không đọc được. Hãy thử lại sau.") from exc
    if not isinstance(data, dict):
        raise ValueError("yt-dlp trả về dữ liệu không đọc được. Hãy thử lại sau.")
    return data


def add_pasted_link(
    paths: AppPaths,
    url: str,
    *,
    actor: str = "ui",
    now_dt: datetime | None = None,
) -> tuple[int, TrendItem]:
    """Validates, reads, stores and queues analysis for one pasted video link."""
    platform, clean_url = classify_video_url(url)
    _check_daily_cap(paths.db_file, now_dt=now_dt)
    data = read_video_metadata(clean_url)
    item = parse_single_video(data, platform=platform, url=clean_url, now_dt=now_dt)
    _count_link(paths.db_file, now_dt=now_dt)
    trend_id = upsert_trend_item(paths.db_file, item, now_dt=now_dt)

    row = query_one(paths.db_file, "SELECT analysis_json FROM trend_items WHERE id = ?", (trend_id,))
    if row is not None and not row.get("analysis_json"):
        enqueue_job(paths.db_file, ANALYSE_TREND_JOB_KIND, ref_id=trend_id)
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn, actor=actor, action="trends.link_added", object_type="trend_item",
            object_id=trend_id, detail=clean_url,
        )
    return trend_id, item


def run_analyse_trend_job(paths: AppPaths, trend_item_id: int) -> str:
    """Job handler for `analyse_trend`: analyse one pasted video, then refresh suggestions."""
    from videocreator.trends.analyse import analyse_trend_item
    from videocreator.trends.suggest import make_suggestions

    row = query_one(paths.db_file, "SELECT analysis_json FROM trend_items WHERE id = ?", (trend_item_id,))
    if row is None:
        return f"Trend item #{trend_item_id} no longer exists"
    if row.get("analysis_json"):
        return f"Trend item #{trend_item_id} was already analysed; nothing to do"
    # Hand-picked videos have their own daily cap, so they skip the scan's download cap.
    analyse_trend_item(paths, trend_item_id, ignore_download_cap=True)
    ref = query_one(
        paths.db_file,
        "SELECT path FROM reference_videos WHERE trend_item_id = ? AND deleted_at IS NULL",
        (trend_item_id,),
    )
    made = make_suggestions(paths)
    how = "with the downloaded video (rea-video)" if ref else "from metrics and caption only (video could not be downloaded)"
    return f"Analysed trend item #{trend_item_id} {how}; suggestions created: {len(made)}"
