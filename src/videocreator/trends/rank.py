"""Transparent within-source trend scoring functions (`FR-TRD-04`, Phase 12)."""
from __future__ import annotations
import math
from datetime import datetime, timezone

from videocreator.timeutil import utc_now
from videocreator.trends.base import TrendItem


def score_trend_item(
    item: TrendItem,
    now_dt: datetime | None = None,
) -> float:
    """Computes within-source score for `item`.

    - Social (`youtube`, `ig_discovery`, `ig_hashtag`):
      `(likes + 2 * comments + views / 100) / max(hours_since_published, 24)`
    - Ads (`ad_library`):
      `days_running * (1.5 if is_active else 1.0) + log10(max(eu_reach, 1))`
      (returns 0.0 if `days_running < 30`)
    """
    base_utc = utc_now(now_dt)
    pub_utc = (
        item.published_at.astimezone(timezone.utc)
        if item.published_at.tzinfo is not None
        else item.published_at.replace(tzinfo=timezone.utc)
    )
    metrics = item.metrics or {}

    if item.source == "ad_library":
        days_running = float(
            metrics.get("days_running")
            or max(0.0, (base_utc - pub_utc).total_seconds() / 86400.0)
        )
        if days_running < 30.0:
            return 0.0
        is_active = bool(metrics.get("is_active", True))
        eu_reach = max(1, int(metrics.get("eu_reach") or metrics.get("eu_total_reach") or 1))
        mult = 1.5 if is_active else 1.0
        return round(days_running * mult + math.log10(eu_reach), 4)

    likes = float(metrics.get("likes") or metrics.get("like_count") or 0.0)
    comments = float(metrics.get("comments") or metrics.get("comment_count") or 0.0)
    views = float(metrics.get("views") or metrics.get("view_count") or 0.0)

    hours_age = max(24.0, (base_utc - pub_utc).total_seconds() / 3600.0)
    raw_score = (likes + 2.0 * comments + views / 100.0) / hours_age
    return round(raw_score, 4)
