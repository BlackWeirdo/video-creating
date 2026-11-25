"""SQLite persistence and workspace-fair queue selection for `muse_tasks` and `muse_storyboards`."""
from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one
from videocreator.db_rows import file_media_url, hydrate_row
from videocreator.workspaces import require_workspace

ACTIVE_MUSE_TASK_STATUSES: tuple[str, ...] = ("pending", "submitted", "importing", "waiting_quota")


def _hydrate_task(row: dict[str, Any]) -> dict[str, Any]:
    out = hydrate_row(
        row,
        json_fields={
            "params": ("params_json", {}),
            "refs": ("refs_json", []),
        },
        bool_fields=("partial",),
    )
    out["media_url"] = file_media_url(out.get("local_path"), empty="")
    return out


def create_muse_task(
    db_file: Path,
    *,
    workspace_id: int,
    kind: str = "video",
    model: str = "muse-video",
    purpose: str = "studio",
    prompt: str,
    params: dict[str, Any] | None = None,
    refs: list[dict[str, Any]] | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    thread_url: str | None = None,
    account_id: str | None = None,
    parent_task_id: int | None = None,
    priority: int = 0,
) -> dict[str, Any]:
    require_workspace(db_file, workspace_id)
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        raise ValueError("Muse task prompt is required")
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO muse_tasks (
                workspace_id, kind, model, purpose, ref_type, ref_id, prompt,
                params_json, refs_json, thread_url, account_id, parent_task_id, priority, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                int(workspace_id),
                kind,
                (model or "muse-video").strip(),
                (purpose or "studio").strip(),
                ref_type,
                int(ref_id) if ref_id is not None else None,
                clean_prompt,
                json.dumps(params or {}, ensure_ascii=False),
                json.dumps(refs or [], ensure_ascii=False),
                thread_url,
                account_id,
                int(parent_task_id) if parent_task_id is not None else None,
                int(priority),
            ),
        )
        tid = int(cur.lastrowid)
    created = get_muse_task(db_file, tid)
    assert created is not None
    return created


def get_muse_task(db_file: Path, task_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM muse_tasks WHERE id = ?", (int(task_id),))
    return _hydrate_task(row) if row else None


def get_muse_task_by_gateway_id(db_file: Path, gateway_task_id: str) -> dict[str, Any] | None:
    row = query_one(
        db_file,
        "SELECT * FROM muse_tasks WHERE gateway_task_id = ?",
        ((gateway_task_id or "").strip(),),
    )
    return _hydrate_task(row) if row else None


def list_muse_tasks(
    db_file: Path,
    *,
    workspace_id: int | None = None,
    status: str | None = None,
    purpose: str | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(int(workspace_id))
    if status:
        clauses.append("status = ?")
        params.append(status.strip())
    if purpose:
        clauses.append("purpose = ?")
        params.append(purpose.strip())
    if ref_type:
        clauses.append("ref_type = ?")
        params.append(ref_type.strip())
    if ref_id is not None:
        clauses.append("ref_id = ?")
        params.append(int(ref_id))

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(500, int(limit))))
    rows = query_all(
        db_file,
        f"SELECT * FROM muse_tasks {where} ORDER BY id DESC LIMIT ?",
        params,
    )
    return [_hydrate_task(r) for r in rows]


def list_tasks_by_status(db_file: Path, status: str) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM muse_tasks WHERE status = ? ORDER BY priority DESC, id ASC",
        (status,),
    )
    return [_hydrate_task(r) for r in rows]


def select_fair_pending_tasks(db_file: Path, *, limit: int) -> list[dict[str, Any]]:
    """Selects up to `limit` pending tasks ordered by priority while interleaving across workspaces."""
    if limit <= 0:
        return []
    rows = query_all(
        db_file,
        "SELECT * FROM muse_tasks WHERE status = 'pending' ORDER BY priority DESC, id ASC LIMIT 500",
    )
    if not rows:
        return []

    by_ws: dict[int, deque[dict[str, Any]]] = {}
    ws_order: list[int] = []
    for r in rows:
        ws_id = int(r["workspace_id"])
        if ws_id not in by_ws:
            by_ws[ws_id] = deque()
            ws_order.append(ws_id)
        by_ws[ws_id].append(_hydrate_task(r))

    picked: list[dict[str, Any]] = []
    while len(picked) < limit and any(by_ws.values()):
        # Pick highest priority head across workspace queues, breaking ties by round-robin ws_order
        non_empty = [ws_id for ws_id in ws_order if by_ws[ws_id]]
        max_prio = max(int(by_ws[ws_id][0]["priority"]) for ws_id in non_empty)
        for ws_id in list(ws_order):
            if len(picked) >= limit:
                break
            q = by_ws[ws_id]
            if q and int(q[0]["priority"]) == max_prio:
                picked.append(q.popleft())
                ws_order.remove(ws_id)
                ws_order.append(ws_id)
                break
    return picked


def update_muse_task(db_file: Path, task_id: int, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        return get_muse_task(db_file, task_id)
    sets = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = []
    for col, val in fields.items():
        sets.append(f"{col} = ?")
        if col in ("params_json", "refs_json") and not isinstance(val, str):
            params.append(json.dumps(val, ensure_ascii=False))
        elif col == "partial" and isinstance(val, bool):
            params.append(1 if val else 0)
        else:
            params.append(val)
    params.append(int(task_id))
    with get_conn(db_file) as conn:
        conn.execute(f"UPDATE muse_tasks SET {', '.join(sets)} WHERE id = ?", params)
    return get_muse_task(db_file, task_id)


def wake_expired_muse_quota_tasks(db_file: Path, now_iso: str) -> int:
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            UPDATE muse_tasks
            SET status = 'pending',
                retry_after = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE status = 'waiting_quota'
              AND (retry_after IS NULL OR retry_after <= ?)
            """,
            (now_iso,),
        )
        return int(cur.rowcount or 0)


def count_active_muse_tasks(
    db_file: Path, *, workspace_id: int | None = None
) -> dict[str, int]:
    empty = {"pending": 0, "submitted": 0, "importing": 0, "waiting_quota": 0, "running_total": 0}
    if not db_file.exists():
        return empty
    try:
        where = "WHERE workspace_id = ?" if workspace_id is not None else ""
        params = (int(workspace_id),) if workspace_id is not None else ()
        rows = query_all(
            db_file,
            f"SELECT status, COUNT(*) AS c FROM muse_tasks {where} GROUP BY status",
            params,
        )
        out = dict(empty)
        for r in rows:
            st = str(r["status"])
            if st in out:
                out[st] = int(r["c"])
        out["running_total"] = out["pending"] + out["submitted"] + out["importing"]
        return out
    except sqlite3.Error:
        return empty


__all__ = [
    "ACTIVE_MUSE_TASK_STATUSES",
    "count_active_muse_tasks",
    "create_muse_task",
    "get_muse_task",
    "get_muse_task_by_gateway_id",
    "list_muse_tasks",
    "list_tasks_by_status",
    "select_fair_pending_tasks",
    "update_muse_task",
    "wake_expired_muse_quota_tasks",
]
