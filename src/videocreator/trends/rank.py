"""Transparent within-source trend scoring functions (`FR-TRD-04`, Phase 12)."""
from __future__ import annotations
import math
from datetime import datetime, timezone

from videocreator.timeutil import utc_now
from videocreator.trends.base import TrendItem


def compute_outlier_multiplier(
    raw_velocity: float,
    *,
    views: float = 0.0,
    author_followers: float = 0.0,
    author_median_velocity: float | None = None,
) -> float:
    """Computes an outlier breakout multiplier (`1.0 .. 3.0`) when a video outperforms its channel's
    historical median velocity or achieves high view-to-follower breakout."""
    if raw_velocity <= 0.0:
        return 1.0

    history_mult = 1.0
    if author_median_velocity is not None and author_median_velocity > 0.0:
        ratio = raw_velocity / author_median_velocity
        if ratio > 1.5:
            history_mult = min(3.0, 1.0 + math.log2(ratio) * 0.5)

    follower_mult = 1.0
    if author_followers >= 200.0 and views > 0.0:
        vf_ratio = views / author_followers
        if vf_ratio >= 2.0:
            follower_mult = min(2.5, 1.0 + math.log10(vf_ratio) * 0.6)

    return round(min(3.0, max(history_mult, follower_mult)), 3)


def score_trend_item(
    item: TrendItem,
    now_dt: datetime | None = None,
    *,
    author_median_velocity: float | None = None,
) -> float:
    """Computes within-source score for `item`.

    - Social (`youtube`, `tiktok`, `facebook`, `ig_discovery`, `ig_hashtag`):
      `((likes + 2 * comments + 4 * shares + 3 * saves + views / 100) / max(hours_age, 24)) * outlier_mult`
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
    shares = float(metrics.get("shares") or metrics.get("share_count") or 0.0)
    saves = float(metrics.get("saves") or metrics.get("collect_count") or metrics.get("save_count") or 0.0)
    views = float(metrics.get("views") or metrics.get("view_count") or 0.0)
    followers = float(metrics.get("author_followers") or 0.0)

    hours_age = max(24.0, (base_utc - pub_utc).total_seconds() / 3600.0)
    raw_velocity = (likes + 2.0 * comments + 4.0 * shares + 3.0 * saves + views / 100.0) / hours_age
    outlier_mult = compute_outlier_multiplier(
        raw_velocity,
        views=views,
        author_followers=followers,
        author_median_velocity=author_median_velocity,
    )
    return round(raw_velocity * outlier_mult, 4)
