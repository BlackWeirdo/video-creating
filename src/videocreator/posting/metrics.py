"""Post performance checkpoint collection (`24h`, `72h`, `7d`) and aggregation (Phase 15)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all
from videocreator.paths import AppPaths
from videocreator.posting.base import Account, MetricsReader
from videocreator.posting.facebook import FacebookPagePoster
from videocreator.posting.instagram import InstagramReelsPoster
from videocreator.posting.threads import ThreadsPoster
from videocreator.posting.tiktok import TikTokPoster
from videocreator.secrets_store import SecretsStore

logger = logging.getLogger("videocreator.posting.metrics")


def _default_metrics_reader(platform: str, secrets: SecretsStore, paths: AppPaths) -> Any:
    if platform == "facebook":
        return FacebookPagePoster(paths, secrets)
    if platform == "instagram":
        return InstagramReelsPoster(paths, secrets)
    if platform == "threads":
        return ThreadsPoster(paths, secrets)
    if platform == "tiktok":
        return TikTokPoster(paths, secrets)
    return None

CHECKPOINT_HOURS: list[tuple[str, float]] = [
    ("24h", 24.0),
    ("72h", 72.0),
    ("7d", 168.0),
]
MAX_COLLECTION_WINDOW_HOURS = 24.0


def due_checkpoints(
    posted_at_iso: str,
    now_dt: datetime,
    existing_checkpoints: set[str],
) -> list[str]:
    """Pure function returning which checkpoints (`24h`, `72h`, `7d`) are due at `now_dt`.

    A checkpoint at `H` hours is due when `H <= age_hours <= H + 24` and not yet recorded (`FR-RPT-02`).
    """
    if not posted_at_iso:
        return []
    try:
        posted_dt = datetime.fromisoformat(posted_at_iso.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except Exception:
        return []

    now_utc = now_dt.astimezone(timezone.utc)
    age_hours = (now_utc - posted_dt).total_seconds() / 3600.0
    due: list[str] = []
    for cp_name, threshold_h in CHECKPOINT_HOURS:
        if cp_name in existing_checkpoints:
            continue
        if threshold_h <= age_hours <= (threshold_h + MAX_COLLECTION_WINDOW_HOURS):
            due.append(cp_name)
    return due


def record_post_metric(
    db_file: Path,
    *,
    post_id: int,
    checkpoint: str,
    metrics: dict[str, int | None],
    fetched_at_iso: str | None = None,
) -> bool:
    """Inserts a `post_metrics` row (`UNIQUE(post_id, checkpoint)`). Missing values stay `NULL`."""
    ts = fetched_at_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO post_metrics
                (post_id, checkpoint, fetched_at, views, likes, comments, shares)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(post_id),
                checkpoint,
                ts,
                metrics.get("views"),
                metrics.get("likes"),
                metrics.get("comments"),
                metrics.get("shares"),
            ),
        )
        return cur.rowcount == 1


def collect_due_metrics(
    paths: AppPaths,
    *,
    now_dt: datetime | None = None,
    reader_overrides: dict[str, MetricsReader] | None = None,
) -> int:
    """Scans `posted` posts and fetches due `24h`/`72h`/`7d` metrics from platform adapters (`FR-RPT-02`).

    Returns the number of newly recorded checkpoint rows.
    """
    base_utc = (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = base_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    secrets = SecretsStore(paths.secrets_file)

    posted_rows = query_all(
        paths.db_file,
        """
        SELECT p.id AS post_id, p.video_id, p.account_id, p.external_post_id, p.posted_at,
               a.id, a.platform, a.external_id, a.name, a.lang, a.slots_json,
               a.secret_key, a.token_expires_at, a.enabled
        FROM posts p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.status = 'posted'
          AND p.posted_at IS NOT NULL
          AND p.external_post_id IS NOT NULL
          AND p.external_post_id != ''
        ORDER BY p.id ASC
        """,
    )
    if not posted_rows:
        return 0

    existing_rows = query_all(
        paths.db_file,
        "SELECT post_id, checkpoint FROM post_metrics",
    )
    existing_map: dict[int, set[str]] = {}
    for er in existing_rows:
        existing_map.setdefault(int(er["post_id"]), set()).add(str(er["checkpoint"]))

    collected = 0
    for row in posted_rows:
        pid = int(row["post_id"])
        ext_post_id = str(row["external_post_id"] or "").strip()
        if not ext_post_id:
            continue

        due_cps = due_checkpoints(
            str(row["posted_at"]),
            base_utc,
            existing_map.get(pid, set()),
        )
        if not due_cps:
            continue

        platform = str(row["platform"])
        account: Account = dict(row)
        reader: Any = (reader_overrides or {}).get(platform)
        if reader is None:
            try:
                reader = _default_metrics_reader(platform, secrets, paths)
            except Exception as exc:
                logger.debug("Could not initialize metrics reader for %s: %s", platform, exc)
                continue

        if reader is None or not hasattr(reader, "fetch_metrics"):
            continue

        try:
            data = reader.fetch_metrics(account, ext_post_id)
        except Exception as exc:
            logger.warning("Metrics fetch failed for post #%d (%s): %s", pid, platform, exc)
            continue

        if not isinstance(data, dict):
            continue

        for cp in due_cps:
            if record_post_metric(
                paths.db_file,
                post_id=pid,
                checkpoint=cp,
                metrics=data,
                fetched_at_iso=now_iso,
            ):
                collected += 1
                existing_map.setdefault(pid, set()).add(cp)

    return collected


def list_performance_rows(db_file: Path) -> list[dict[str, Any]]:
    """Returns posted items enriched with `24h`, `72h`, `7d` checkpoints and formula/suggestion metadata."""
    posts = query_all(
        db_file,
        """
        SELECT p.id AS post_id, p.video_id, p.external_post_id, p.permalink, p.posted_at,
               a.platform, a.name AS account_name,
               v.plan_json, v.suggestion_id
        FROM posts p
        JOIN accounts a ON p.account_id = a.id
        JOIN videos v ON p.video_id = v.id
        WHERE p.status IN ('posted', 'needs_user_action')
        ORDER BY p.posted_at DESC, p.id DESC
        """,
    )
    metric_rows = query_all(db_file, "SELECT * FROM post_metrics")
    by_post_cp: dict[tuple[int, str], dict[str, Any]] = {}
    for m in metric_rows:
        by_post_cp[(int(m["post_id"]), str(m["checkpoint"]))] = m

    items: list[dict[str, Any]] = []
    for p in posts:
        pid = int(p["post_id"])
        try:
            plan = json.loads(str(p.get("plan_json") or "{}"))
        except Exception:
            plan = {}
        formula = str(plan.get("formula") or "hook-first")
        title = str(plan.get("title") or f"Video #{p['video_id']}")

        cp_map: dict[str, dict[str, Any] | None] = {}
        for cp_name, _ in CHECKPOINT_HOURS:
            cp_map[cp_name] = by_post_cp.get((pid, cp_name))

        items.append(
            {
                "post_id": pid,
                "video_id": int(p["video_id"]),
                "title": title,
                "formula": formula,
                "from_suggestion": p.get("suggestion_id") is not None,
                "suggestion_id": p.get("suggestion_id"),
                "platform": p["platform"],
                "account_name": p["account_name"],
                "permalink": p.get("permalink"),
                "posted_at": p.get("posted_at"),
                "checkpoints": cp_map,
            }
        )
    return items
