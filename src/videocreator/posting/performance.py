"""Rows of the performance page: posts with their latest collected metrics."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from videocreator.db import query_all
from videocreator.jsonutil import loads_or
from videocreator.posting.metrics import CHECKPOINT_HOURS


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
        plan = loads_or(p.get("plan_json"), {})
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
