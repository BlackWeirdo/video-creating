"""Trend scanning service: iterates watch_items, fetches from adapters, scores, and upserts (Phase 12)."""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videocreator.db import get_write_conn, query_all
from videocreator.logging_setup import redact_text
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now
from videocreator.trends.ad_library import MetaAdLibrarySource
from videocreator.trends.apify import APIFY_SOURCE_CLASSES, APIFY_TOKEN_KEY
from videocreator.trends.base import TrendItem, TrendSource, WatchItem
from statistics import median
from videocreator.trends.facebook import FacebookSource
from videocreator.trends.ig_discovery import IGBusinessDiscoverySource
from videocreator.trends.ig_hashtag import IGHashtagSource
from videocreator.trends.rank import score_trend_item
from videocreator.trends.youtube import YouTubeTrendSource

logger = logging.getLogger("videocreator.trends.scan")


def build_trend_sources(
    paths: AppPaths, secrets_store: SecretsStore | None = None
) -> dict[str, TrendSource]:
    sec = secrets_store or SecretsStore(paths.secrets_file)
    sources: dict[str, TrendSource] = {
        "youtube": YouTubeTrendSource(paths, sec),
        "ig_discovery": IGBusinessDiscoverySource(paths, sec),
        "ad_library": MetaAdLibrarySource(paths, sec),
        "ig_hashtag": IGHashtagSource(paths, sec),
        "facebook": FacebookSource(paths, sec),
    }
    # With an Apify token, the same source names are served by Apify scrapers (owner decision
    # 2026-11-14); TikTok exists only there. Without it, the official adapters above stay.
    if sec.has(APIFY_TOKEN_KEY):
        for cls in APIFY_SOURCE_CLASSES:
            sources[cls.name] = cls(paths, sec)
    return sources


def upsert_trend_item(
    db_file: Path,
    item: TrendItem,
    *,
    now_dt: datetime | None = None,
) -> int:
    """Computes `score` (with channel Outlier boost) for `item` and upserts into `trend_items`."""
    base_utc = utc_now(now_dt)
    pub_utc = (
        item.published_at.astimezone(timezone.utc)
        if item.published_at.tzinfo is not None
        else item.published_at.replace(tzinfo=timezone.utc)
    )
    pub_iso = pub_utc.strftime(UTC_ISO_FORMAT)
    fetched_iso = base_utc.strftime(UTC_ISO_FORMAT)
    metrics_dict = dict(item.metrics or {})

    with get_write_conn(db_file) as conn:
        author_median: float | None = None
        if item.source != "ad_library" and item.author.strip():
            peer_rows = conn.execute(
                """
                SELECT score, metrics_json FROM trend_items
                WHERE source = ? AND author = ? AND external_id != ? AND score > 0
                ORDER BY id DESC LIMIT 20
                """,
                (item.source, item.author.strip(), item.external_id),
            ).fetchall()
            if len(peer_rows) >= 2:
                base_velocities: list[float] = []
                for pr in peer_rows:
                    pscore = float(pr["score"] or 0.0)
                    pmult = 1.0
                    try:
                        pm = json.loads(str(pr["metrics_json"] or "{}"))
                        if isinstance(pm, dict) and float(pm.get("outlier_mult") or 1.0) > 0:
                            pmult = float(pm.get("outlier_mult") or 1.0)
                    except Exception:
                        pmult = 1.0
                    base_velocities.append(pscore / max(1.0, pmult))
                author_median = float(median(base_velocities))

        base_score = score_trend_item(item, now_dt=base_utc, author_median_velocity=None)
        score = (
            score_trend_item(item, now_dt=base_utc, author_median_velocity=author_median)
            if author_median is not None
            else base_score
        )
        raw_no_boost = score_trend_item(
            TrendItem(
                source=item.source,
                external_id=item.external_id,
                url=item.url,
                author=item.author,
                caption=item.caption,
                published_at=item.published_at,
                metrics={k: v for k, v in metrics_dict.items() if k != "author_followers"},
                video_url=item.video_url,
            ),
            now_dt=base_utc,
        )
        if item.source != "ad_library" and raw_no_boost > 0 and score > raw_no_boost * 1.02:
            metrics_dict["outlier_mult"] = round(score / raw_no_boost, 2)

        existing = conn.execute(
            "SELECT id, metrics_json FROM trend_items WHERE source = ? AND external_id = ?",
            (item.source, item.external_id),
        ).fetchone()
        if existing and existing["metrics_json"] and "pinned" not in metrics_dict:
            try:
                prev_metrics = json.loads(str(existing["metrics_json"]))
                if isinstance(prev_metrics, dict) and prev_metrics.get("pinned"):
                    metrics_dict["pinned"] = True
            except Exception:
                pass
        metrics_str = json.dumps(metrics_dict, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO trend_items (
                source, external_id, url, author, caption,
                published_at, metrics_json, score, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                url = excluded.url,
                author = excluded.author,
                caption = excluded.caption,
                metrics_json = excluded.metrics_json,
                score = excluded.score,
                fetched_at = excluded.fetched_at
            """,
            (
                item.source,
                item.external_id,
                item.url,
                item.author,
                item.caption,
                pub_iso,
                metrics_str,
                score,
                fetched_iso,
            ),
        )
        row = conn.execute(
            "SELECT id FROM trend_items WHERE source = ? AND external_id = ?",
            (item.source, item.external_id),
        ).fetchone()
        return int(row["id"]) if row else 0


def _store_fetched_items(paths: AppPaths, items: list[TrendItem], now_dt: datetime | None) -> int:
    """Upserts fetched items; an Ad Library item that scores zero is not kept. Returns how many were stored."""
    stored = 0
    for item in items:
        if item.source == "ad_library" and score_trend_item(item, now_dt=now_dt) <= 0.0:
            continue
        upsert_trend_item(paths.db_file, item, now_dt=now_dt)
        stored += 1
    return stored


def _is_rate_limit_error(error_text: str) -> bool:
    """Rate limits (429 / 613) or quota exhaustion stop that source for the rest of the scan."""
    lower = error_text.lower()
    return "429" in error_text or "613" in error_text or "quota" in lower or "giới hạn" in lower


def scan_all(
    paths: AppPaths,
    *,
    source_overrides: dict[str, TrendSource] | None = None,
    now_dt: datetime | None = None,
) -> dict[str, Any]:
    """Scans all enabled `watch_items`. Errors in one source never block other sources (`FR-TRD-03`)."""
    sources = source_overrides or build_trend_sources(paths)
    watch_rows = query_all(
        paths.db_file,
        "SELECT * FROM watch_items WHERE enabled = 1 ORDER BY id ASC",
    )

    upserted_count = 0
    errors_by_source: dict[str, str] = {}
    stopped_sources: set[str] = set()

    for wr in watch_rows:
        src_name = str(wr["source"])
        if src_name in stopped_sources:
            continue

        adapter = sources.get(src_name)
        if adapter is None:
            errors_by_source[src_name] = f"Nguồn '{src_name}' không tồn tại"
            stopped_sources.add(src_name)
            continue

        ok, reason = adapter.status()
        if not ok:
            errors_by_source[src_name] = reason or "chưa bật"
            stopped_sources.add(src_name)
            continue

        watch = WatchItem(
            id=int(wr["id"]),
            source=src_name,
            kind=str(wr["kind"]),
            value=str(wr["value"]),
            enabled=bool(wr["enabled"]),
        )
        try:
            upserted_count += _store_fetched_items(paths, adapter.fetch(watch), now_dt)
        except Exception as exc:
            err_str = redact_text(str(exc))
            logger.warning("Trend scan error on %s (%s): %s", src_name, watch.value, err_str)
            errors_by_source[src_name] = err_str
            if _is_rate_limit_error(err_str):
                stopped_sources.add(src_name)

    return {
        "upserted": upserted_count,
        "errors": errors_by_source,
    }
