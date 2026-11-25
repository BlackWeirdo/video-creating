"""Autopilot rule CRUD, hydration, and workspace `content_policy` validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import hydrate_row
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import count_workspace_shots
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.workspaces import require_workspace

VALID_AUTOPILOT_MODES: frozenset[str] = frozenset(
    {"suggestions", "products_ab", "rss_feed", "localize_trends"}
)


def validate_autopilot_policy(
    db_file: Path, workspace_id: int, source_mode: str
) -> dict[str, Any]:
    clean_mode = (source_mode or "").strip().lower()
    if clean_mode not in VALID_AUTOPILOT_MODES:
        raise ValueError(f"Unsupported autopilot source_mode '{source_mode}'")

    ws = require_workspace(db_file, workspace_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    if policy == "strict_footage" and clean_mode == "localize_trends":
        raise PermissionError(
            "Workspace 'strict_footage' không cho phép Autopilot chế độ 'localize_trends'."
        )
    if (
        policy == "strict_footage"
        and clean_mode == "rss_feed"
        and count_workspace_shots(db_file, workspace_id) == 0
    ):
        raise PermissionError(
            "Workspace 'strict_footage' cần ít nhất 1 shot footage thật để chạy Autopilot 'rss_feed'."
        )
    return ws


def hydrate_rule(row: dict[str, Any]) -> dict[str, Any]:
    out = hydrate_row(row, bool_fields={"enabled": ("enabled", True)})
    out["target_account_ids"] = [
        int(x) for x in loads_or(row.get("target_account_ids_json"), []) if str(x).isdigit()
    ]
    return out


def list_autopilot_rules(
    db_file: Path, *, workspace_id: int | None = None
) -> list[dict[str, Any]]:
    if workspace_id is not None:
        rows = query_all(
            db_file,
            "SELECT * FROM autopilot_rules WHERE workspace_id = ? ORDER BY id DESC",
            (int(workspace_id),),
        )
    else:
        rows = query_all(
            db_file, "SELECT * FROM autopilot_rules ORDER BY workspace_id ASC, id DESC"
        )
    return [hydrate_rule(r) for r in rows]


def get_autopilot_rule(db_file: Path, rule_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM autopilot_rules WHERE id = ?", (int(rule_id),))
    return hydrate_rule(row) if row else None


def list_autopilot_runs(
    db_file: Path,
    *,
    workspace_id: int | None = None,
    rule_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(int(workspace_id))
    if rule_id is not None:
        clauses.append("rule_id = ?")
        params.append(int(rule_id))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(300, int(limit))))
    return query_all(
        db_file,
        f"SELECT * FROM autopilot_runs {where} ORDER BY id DESC LIMIT ?",
        params,
    )


def create_autopilot_rule(
    paths: AppPaths,
    *,
    workspace_id: int,
    name: str,
    source_mode: str,
    feed_url: str = "",
    target_account_ids: list[int] | None = None,
    daily_cap: int = 3,
    min_quality_score: float = 8.0,
    style_preset: str = "tiktok_karaoke",
    aspect_ratio: str = "9:16",
    interval_minutes: int = 60,
    enabled: bool = True,
    actor: str = "api",
) -> dict[str, Any]:
    validate_autopilot_policy(paths.db_file, workspace_id, source_mode)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Autopilot rule name is required")
    if source_mode == "rss_feed" and not (feed_url or "").strip():
        raise ValueError("RSS/Atom feed URL or local file path is required for 'rss_feed' mode")

    cap = max(1, min(20, int(daily_cap)))
    interval_m = max(1, int(interval_minutes))
    style = resolve_style_preset(paths.db_file, style_preset)["id"]
    acct_ids = [int(a) for a in (target_account_ids or []) if int(a) > 0]

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO autopilot_rules (
                workspace_id, name, enabled, source_mode, feed_url,
                target_account_ids_json, daily_cap, min_quality_score,
                style_preset, aspect_ratio, interval_minutes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_name,
                1 if enabled else 0,
                source_mode.strip().lower(),
                feed_url.strip(),
                json.dumps(acct_ids),
                cap,
                float(min_quality_score),
                style,
                (aspect_ratio or "9:16").strip() or "9:16",
                interval_m,
            ),
        )
        rule_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_autopilot_rule",
            object_type="autopilot_rule",
            object_id=rule_id,
            detail=f"{clean_name} ({source_mode}, cap={cap})",
        )
    rule = get_autopilot_rule(paths.db_file, rule_id)
    assert rule is not None
    return rule


def update_autopilot_rule(
    paths: AppPaths,
    rule_id: int,
    *,
    name: str | None = None,
    enabled: bool | None = None,
    feed_url: str | None = None,
    target_account_ids: list[int] | None = None,
    daily_cap: int | None = None,
    min_quality_score: float | None = None,
    style_preset: str | None = None,
    aspect_ratio: str | None = None,
    interval_minutes: int | None = None,
) -> dict[str, Any] | None:
    existing = get_autopilot_rule(paths.db_file, rule_id)
    if existing is None:
        return None
    sets: list[str] = []
    params: list[Any] = []
    if name is not None and name.strip():
        sets.append("name = ?")
        params.append(name.strip())
    if enabled is not None:
        sets.append("enabled = ?")
        params.append(1 if enabled else 0)
    if feed_url is not None:
        sets.append("feed_url = ?")
        params.append(feed_url.strip())
    if target_account_ids is not None:
        sets.append("target_account_ids_json = ?")
        params.append(json.dumps([int(a) for a in target_account_ids if int(a) > 0]))
    if daily_cap is not None:
        sets.append("daily_cap = ?")
        params.append(max(1, min(20, int(daily_cap))))
    if min_quality_score is not None:
        sets.append("min_quality_score = ?")
        params.append(float(min_quality_score))
    if style_preset is not None and style_preset.strip():
        style = resolve_style_preset(paths.db_file, style_preset)["id"]
        sets.append("style_preset = ?")
        params.append(style)
    if aspect_ratio is not None and aspect_ratio.strip():
        sets.append("aspect_ratio = ?")
        params.append(aspect_ratio.strip())
    if interval_minutes is not None:
        sets.append("interval_minutes = ?")
        params.append(max(1, int(interval_minutes)))

    if sets:
        params.append(int(rule_id))
        with get_conn(paths.db_file) as conn:
            conn.execute(
                f"UPDATE autopilot_rules SET {', '.join(sets)} WHERE id = ?",
                params,
            )
    return get_autopilot_rule(paths.db_file, rule_id)


def delete_autopilot_rule(paths: AppPaths, rule_id: int) -> bool:
    existing = get_autopilot_rule(paths.db_file, rule_id)
    if existing is None:
        return False
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM autopilot_rules WHERE id = ?", (int(rule_id),))
        record_audit(
            conn,
            actor="autopilot",
            action="delete_autopilot_rule",
            object_type="autopilot_rule",
            object_id=int(rule_id),
        )
    return True
