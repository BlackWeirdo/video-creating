"""Instruction presets for the AI roles (`FR-PLN-07`): create, list, export, import."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all


def create_preset(db_file: Path, *, name: str, kind: str, body: str) -> int:
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO presets (name, kind, body)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                kind = excluded.kind,
                body = excluded.body
            """,
            (name.strip(), kind.strip(), body.strip()),
        )
        row = conn.execute("SELECT id FROM presets WHERE name = ?", (name.strip(),)).fetchone()
        return int(row["id"]) if row else int(cur.lastrowid or 0)


def list_presets(db_file: Path) -> list[dict[str, Any]]:
    return query_all(db_file, "SELECT * FROM presets ORDER BY id ASC")


def export_presets_json(db_file: Path) -> str:
    rows = list_presets(db_file)
    export_items = [
        {"name": r["name"], "kind": r["kind"], "body": r["body"]}
        for r in rows
    ]
    return json.dumps({"presets": export_items}, ensure_ascii=False, indent=2)


def import_presets_json(db_file: Path, raw_json: str) -> int:
    data = json.loads(raw_json)
    items = data.get("presets") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("Invalid presets JSON format")
    count = 0
    for item in items:
        if isinstance(item, dict) and item.get("name") and item.get("body"):
            create_preset(
                db_file,
                name=str(item["name"]),
                kind=str(item.get("kind") or "writer"),
                body=str(item["body"]),
            )
            count += 1
    return count
