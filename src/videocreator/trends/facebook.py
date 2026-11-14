"""Facebook Page / Profile watch sources (manual reference list).

Meta offers no way to list another Page's or Profile's videos without the Page Public Content
Access feature (app review), and yt-dlp has no Page listing extractor (`Unsupported URL`,
checked 2026-11-14). So these watch items are a saved list of sources the owner opens by hand;
good videos found there come in through pasted links (`trends/links.py`, `/link` on Telegram).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.trends.base import TrendItem, WatchItem

FACEBOOK_HOSTS = frozenset(
    {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "mbasic.facebook.com"}
)
# First path segments that are never a Page/Profile name.
_RESERVED_SEGMENTS = frozenset(
    {
        "reel", "reels", "watch", "videos", "video.php", "share", "groups", "events", "photo",
        "photo.php", "story.php", "permalink.php", "hashtag", "marketplace", "gaming", "login",
        "login.php", "pages", "help", "ads", "business", "search", "plugins", "sharer", "dialog",
    }
)
_PAGE_NAME = re.compile(r"^[A-Za-z0-9.\-]{2,80}$")

FACEBOOK_MANUAL_REASON = (
    "chưa bật tự động: Facebook không cho app đọc Reels/video của Fanpage hay Profile khác "
    "khi chưa được Meta duyệt quyền Page Public Content Access. Mở trang, chép link Reel hay "
    "rồi dán vào ô 'Thêm video theo link' trên trang Xu hướng (hoặc /link trên Telegram)."
)


def normalize_facebook_source(value: str) -> str:
    """Returns a canonical `https://www.facebook.com/...` link for a Page or Profile.

    Accepts a Page/Profile URL, a bare username, or `profile.php?id=<digits>`. Rejects video,
    group and other non-profile links with a Vietnamese message (`ValueError`).
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Hãy nhập link Fanpage hoặc Profile Facebook.")
    if "://" not in raw:
        if _PAGE_NAME.match(raw.lstrip("@")) and raw.lstrip("@").lower() not in _RESERVED_SEGMENTS:
            return f"https://www.facebook.com/{raw.lstrip('@')}"
        raise ValueError("Tên trang Facebook không hợp lệ. Nhập dạng https://www.facebook.com/tentrang")

    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in FACEBOOK_HOSTS:
        raise ValueError("Chỉ nhận link facebook.com (Fanpage hoặc Profile).")
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        raise ValueError("Link chưa có tên trang. Nhập dạng https://www.facebook.com/tentrang")

    first = segments[0]
    if first.lower() == "profile.php":
        profile_id = (parse_qs(parts.query).get("id") or [""])[0]
        if profile_id.isdigit():
            return f"https://www.facebook.com/profile.php?id={profile_id}"
        raise ValueError("Link profile.php thiếu id số.")
    if first.lower() == "people" and len(segments) >= 3 and segments[2].isdigit():
        return f"https://www.facebook.com/profile.php?id={segments[2]}"
    if first.lower() in _RESERVED_SEGMENTS:
        raise ValueError(
            "Đây là link video/bài viết, không phải trang. Hãy dán link này vào ô 'Thêm video theo link' trên trang Xu hướng."
        )
    if not _PAGE_NAME.match(first):
        raise ValueError("Tên trang Facebook không hợp lệ.")
    return f"https://www.facebook.com/{first}"


class FacebookSource:
    """Saved Facebook Pages (`page`) and Profiles (`account`); never fetched automatically."""

    name = "facebook"
    kinds = ("page", "account")

    def __init__(self, paths: AppPaths, secrets_store: SecretsStore | None = None) -> None:
        self.paths = paths
        self.secrets = secrets_store

    def status(self) -> tuple[bool, str | None]:
        return False, FACEBOOK_MANUAL_REASON

    def fetch(self, watch: WatchItem) -> list[TrendItem]:
        raise RuntimeError(FACEBOOK_MANUAL_REASON)
