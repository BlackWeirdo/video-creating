"""Per-platform caption limits (`BR-CAP-01`) applied to AI output and to edits from the web forms."""
from __future__ import annotations

from typing import Any, Iterable

from videocreator.pipeline.plan_schema import PLATFORM_CHAR_LIMITS, PLATFORM_HASHTAG_LIMITS

CAPTION_PLATFORMS: tuple[str, ...] = ("facebook", "instagram", "threads", "tiktok")


def clean_hashtags(raw_tags: Iterable[str], max_tags: int) -> list[str]:
    """Non-empty tags with a leading `#`, at most `max_tags` of them."""
    clean_tags: list[str] = []
    for raw in raw_tags:
        tag = raw.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        clean_tags.append(tag)
        if len(clean_tags) >= max_tags:
            break
    return clean_tags


def clean_caption(platform: str, text: str, raw_tags: Iterable[str]) -> dict[str, Any]:
    """Caption of one platform cut to its character and hashtag limits."""
    return {
        "text": text.strip()[: PLATFORM_CHAR_LIMITS[platform]],
        "hashtags": clean_hashtags(raw_tags, PLATFORM_HASHTAG_LIMITS[platform]),
    }


def apply_caption_form(form: Any, captions: dict[str, Any]) -> bool:
    """Updates `captions` from `caption_<platform>_text` / `_hashtags` form fields; True when any was sent."""
    changed = False
    for platform in CAPTION_PLATFORMS:
        cap_text = form.get(f"caption_{platform}_text")
        cap_tags = form.get(f"caption_{platform}_hashtags")
        if cap_text is None and cap_tags is None:
            continue
        raw_tags = str(cap_tags or "").replace(",", " ").split()
        captions[platform] = clean_caption(platform, str(cap_text or ""), raw_tags)
        changed = True
    return changed
