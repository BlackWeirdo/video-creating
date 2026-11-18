"""Pure mappers from Apify actor items to `TrendItem` (tested on real samples in `tests/samples/apify_*.json`)."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from videocreator.timeutil import utc_now
from videocreator.trends.base import TrendItem


def _parse_timestamp(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)) or str(ts).isdigit():
            return datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OSError):
        return None


def map_tiktok(item: dict[str, Any]) -> TrendItem | None:
    if item.get("isSlideshow") or not item.get("id") or not item.get("webVideoUrl"):
        return None
    published = _parse_timestamp(item.get("createTimeISO") or item.get("createTime"))
    if published is None:
        return None
    author = item.get("authorMeta") or {}
    metrics: dict[str, Any] = {
        "views": int(item.get("playCount") or 0),
        "likes": int(item.get("diggCount") or 0),
        "comments": int(item.get("commentCount") or 0),
        "shares": int(item.get("shareCount") or 0),
        "saves": int(item.get("collectCount") or 0),
        "duration_s": float((item.get("videoMeta") or {}).get("duration") or 0),
        "is_ad": bool(item.get("isAd")),
    }
    fans = int(author.get("fans") or author.get("followers") or 0)
    if fans > 0:
        metrics["author_followers"] = fans
    return TrendItem(
        source="tiktok",
        external_id=str(item["id"]),
        url=str(item["webVideoUrl"]),
        author=str(author.get("name") or author.get("nickName") or ""),
        caption=str(item.get("text") or "")[:1000],
        published_at=published,
        metrics=metrics,
        video_url=str(item["webVideoUrl"]),
    )


def map_instagram(item: dict[str, Any], *, source: str) -> TrendItem | None:
    if item.get("type") != "Video" or not item.get("url"):
        return None
    published = _parse_timestamp(item.get("timestamp"))
    if published is None:
        return None
    views = item.get("videoPlayCount") or item.get("igPlayCount") or item.get("videoViewCount") or 0
    metrics: dict[str, Any] = {
        "views": int(views),
        "likes": int(item.get("likesCount") or 0),
        "comments": int(item.get("commentsCount") or 0),
        "shares": int(item.get("sharesCount") or 0),
        "saves": int(item.get("savesCount") or item.get("savedCount") or 0),
        "duration_s": round(float(item.get("videoDuration") or 0), 2),
    }
    followers = int(item.get("ownerFollowersCount") or item.get("followersCount") or 0)
    if followers > 0:
        metrics["author_followers"] = followers
    return TrendItem(
        source=source,
        external_id=str(item.get("shortCode") or item.get("id")),
        url=str(item["url"]),
        author=str(item.get("ownerUsername") or item.get("ownerFullName") or ""),
        caption=str(item.get("caption") or "")[:1000],
        published_at=published,
        metrics=metrics,
        video_url=str(item["url"]),
    )


def map_facebook_reel(item: dict[str, Any]) -> TrendItem | None:
    url = str(item.get("shareable_url") or "")
    m = re.search(r"/reel/(\d+)", url)
    published = _parse_timestamp(item.get("time"))
    if not m or published is None:
        return None
    video = item.get("video") or {}
    owner = item.get("video_owner") or {}
    metrics: dict[str, Any] = {
        "views": int(item.get("playCountRounded") or item.get("playCount") or 0),
        "likes": int(item.get("likesCount") or item.get("likes") or item.get("reactionCount") or 0),
        "comments": int(item.get("commentsCount") or item.get("comments") or 0),
        "shares": int(item.get("sharesCount") or item.get("shares") or 0),
        "duration_s": round(float(video.get("playable_duration_in_ms") or 0) / 1000.0, 2),
    }
    followers = int(owner.get("followers_count") or owner.get("followersCount") or 0)
    if followers > 0:
        metrics["author_followers"] = followers
    return TrendItem(
        source="facebook",
        external_id=m.group(1),
        url=f"https://www.facebook.com/reel/{m.group(1)}",
        author=str(owner.get("name") or ""),
        caption=str(item.get("text") or "")[:1000],
        published_at=published,
        metrics=metrics,
        video_url=f"https://www.facebook.com/reel/{m.group(1)}",
    )


def map_meta_ad(item: dict[str, Any], *, now_dt: datetime | None = None) -> TrendItem | None:
    """Video ads only (images cannot be analysed as video). Score uses days running (`rank.py`)."""
    ad_id = str(item.get("adArchiveID") or item.get("adArchiveId") or "")
    snap = item.get("snapshot") or {}
    has_video = bool(snap.get("videos")) or any((c or {}).get("videoHdUrl") or (c or {}).get("videoSdUrl") for c in snap.get("cards") or [])
    started = _parse_timestamp(item.get("startDate") or item.get("startDateFormatted"))
    if not ad_id or not has_video or started is None:
        return None
    now = utc_now(now_dt)
    body = snap.get("body")
    text = body.get("text") if isinstance(body, dict) else body
    return TrendItem(
        source="ad_library",
        external_id=ad_id,
        url=f"https://www.facebook.com/ads/library/?id={ad_id}",
        author=str(item.get("pageName") or snap.get("pageName") or ""),
        caption=str(text or snap.get("title") or "")[:1000],
        published_at=started,
        metrics={
            "days_running": round(max(0.0, (now - started).total_seconds() / 86400.0), 1),
            "is_active": bool(item.get("isActive")),
            "platforms": item.get("publisherPlatform") or [],
            "page_id": str(item.get("pageID") or item.get("pageId") or ""),
        },
        video_url=f"https://www.facebook.com/ads/library/?id={ad_id}",
    )


def meta_ads_library_url(kind: str, value: str, country: str) -> str:
    base = "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&media_type=video"
    c = quote((country or "VN").upper())
    if kind == "page":
        return f"{base}&country={c}&view_all_page_id={quote(value)}&search_type=page"
    # Exact phrase: "keyword_unordered" matched single words and returned unrelated ads (seen 2026-11-14).
    return f"{base}&country={c}&q={quote(value)}&search_type=keyword_exact_phrase"


def facebook_reels_url(page_or_profile: str) -> str:
    if "profile.php?id=" in page_or_profile:
        return f"{page_or_profile}&sk=reels_tab"
    return page_or_profile.rstrip("/") + "/reels/"
