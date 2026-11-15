"""Pure parsing of pasted Facebook/Instagram video links and of yt-dlp metadata."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from videocreator.timeutil import utc_now
from videocreator.trends.base import TrendItem
from videocreator.trends.facebook import FACEBOOK_HOSTS

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
        published = utc_now(now_dt)
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
