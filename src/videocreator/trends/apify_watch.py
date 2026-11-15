"""Canonical watch values (handles, hashtags, page ids) for the Apify-backed trend sources."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from videocreator.trends.facebook import normalize_facebook_source

HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,60}$")


def _strip_handle(value: str, host_word: str) -> str:
    raw = (value or "").strip()
    if "://" in raw:
        parts = urlsplit(raw)
        if host_word not in (parts.hostname or ""):
            raise ValueError(f"Link không thuộc {host_word}.")
        segs = [s for s in parts.path.split("/") if s]
        raw = segs[0] if segs else ""
    raw = raw.lstrip("@#").strip()
    if not HANDLE_RE.match(raw):
        raise ValueError("Tên tài khoản/hashtag không hợp lệ (chỉ chữ, số, dấu chấm, gạch dưới).")
    return raw


def normalize_apify_watch(source: str, kind: str, value: str) -> str:
    """Canonical watch value for an Apify-backed source (raises `ValueError` in Vietnamese)."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Giá trị theo dõi không được rỗng.")
    if source == "facebook":
        return normalize_facebook_source(value)
    if kind == "keyword":
        return value[:100]
    if source == "tiktok":
        return _strip_handle(value, "tiktok.com")
    if source in ("ig_hashtag", "ig_discovery"):
        return _strip_handle(value, "instagram.com")
    if source == "ad_library" and kind == "page":
        digits = re.sub(r"\D", "", value) if "view_all_page_id" not in value else value.split("view_all_page_id=")[1].split("&")[0]
        if not (digits.isascii() and digits.isdigit()):
            raise ValueError("Page quảng cáo: nhập mã Page dạng số (xem trong Thư viện quảng cáo).")
        return digits
    return value
