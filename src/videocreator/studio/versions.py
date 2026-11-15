"""Version history of a Studio session (`versions_json`)."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_one
from videocreator.jsonutil import loads_or
from videocreator.timeutil import UTC_ISO_FORMAT


def append_studio_version(
    db_file: Path,
    session_id: int,
    *,
    prompt: str,
    output_path: str | None,
    cost_usd: float = 0.0,
    session_ref: str | None = None,
    status: str = "done",
) -> dict[str, Any]:
    """Appends a new version entry into `studio_sessions.versions_json` (`FR-STD-08`)."""
    row = query_one(db_file, "SELECT * FROM studio_sessions WHERE id = ?", (session_id,))
    if row is None:
        raise LookupError(f"Studio session #{session_id} not found")

    versions = loads_or(row.get("versions_json"), [])

    ver_entry = {
        "version": len(versions) + 1,
        "at": datetime.now(timezone.utc).strftime(UTC_ISO_FORMAT),
        "prompt": prompt,
        "output_path": output_path,
        "cost_usd": round(float(cost_usd), 4),
    }
    versions.append(ver_entry)
    total_cost = round(float(row.get("cost_usd") or 0.0) + float(cost_usd), 4)

    with get_conn(db_file) as conn:
        conn.execute(
            """
            UPDATE studio_sessions
            SET status = ?,
                cost_usd = ?,
                session_ref = COALESCE(?, session_ref),
                versions_json = ?
            WHERE id = ?
            """,
            (
                status,
                total_cost,
                session_ref,
                json.dumps(versions, ensure_ascii=False),
                session_id,
            ),
        )
    return ver_entry
