"""Trend scanning service: iterates watch_items, fetches from adapters, scores, and upserts (Phase 12)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.trends.ad_library import MetaAdLibrarySource
from videocreator.trends.base import TrendItem, TrendSource, WatchItem
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
    return {
        "youtube": YouTubeTrendSource(paths, sec),
        "ig_discovery": IGBusinessDiscoverySource(paths, sec),
        "ad_library": MetaAdLibrarySource(paths, sec),
        "ig_hashtag": IGHashtagSource(paths, sec),
        "facebook": FacebookSource(paths, sec),
    }


def upsert_trend_item(
    db_file: Path,
    item: TrendItem,
    *,
    now_dt: datetime | None = None,
) -> int:
    """Computes `score` for `item` and upserts into `trend_items` (`UNIQUE(source, external_id)`)."""
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    pub_utc = (
        item.published_at.astimezone(timezone.utc)
        if item.published_at.tzinfo is not None
        else item.published_at.replace(tzinfo=timezone.utc)
    )
    score = score_trend_item(item, now_dt=base_utc)
    pub_iso = pub_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched_iso = base_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    metrics_str = json.dumps(item.metrics or {}, ensure_ascii=False)

    with get_conn(db_file) as conn:
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
            items = adapter.fetch(watch)
            for it in items:
                if it.source == "ad_library" and score_trend_item(it, now_dt=now_dt) <= 0.0:
                    continue
                upsert_trend_item(paths.db_file, it, now_dt=now_dt)
                upserted_count += 1
        except Exception as exc:
            err_str = str(exc)
            logger.warning("Trend scan error on %s (%s): %s", src_name, watch.value, err_str)
            errors_by_source[src_name] = err_str
            # Rate limits (429 / 613) or quota exhaustion stop that source for the rest of the scan
            if "429" in err_str or "613" in err_str or "quota" in err_str.lower() or "giới hạn" in err_str.lower():
                stopped_sources.add(src_name)

    return {
        "upserted": upserted_count,
        "errors": errors_by_source,
    }
