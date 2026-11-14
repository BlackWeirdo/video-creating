"""Provider cooldown / resting state management in SQLite (Phase 18)."""
from __future__ import annotations

import time
from pathlib import Path

from videocreator.db import get_conn, query_all, query_one


def is_provider_resting(
    db_file: Path,
    provider_name: str,
    *,
    now_ts: int | None = None,
) -> tuple[bool, int | None]:
    """Returns `(is_resting, resting_until_unix_ts)` for `provider_name`."""
    current = int(now_ts if now_ts is not None else time.time())
    row = query_one(
        db_file,
        "SELECT resting_until FROM provider_state WHERE name = ?",
        (provider_name,),
    )
    if row is None or row.get("resting_until") is None:
        return False, None
    try:
        until = int(row["resting_until"])
    except (ValueError, TypeError):
        return False, None
    if until > current:
        return True, until
    return False, None


def mark_provider_resting(
    db_file: Path,
    provider_name: str,
    *,
    duration_s: int = 3600,
    error_msg: str = "",
    now_ts: int | None = None,
) -> int:
    """Marks a provider as resting until `now_ts + duration_s` due to quota exhaustion."""
    current = int(now_ts if now_ts is not None else time.time())
    until = current + max(1, int(duration_s))
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO provider_state (name, resting_until, last_error)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                resting_until = excluded.resting_until,
                last_error = excluded.last_error
            """,
            (provider_name, str(until), error_msg[:500]),
        )
    return until


def mark_provider_error(
    db_file: Path,
    provider_name: str,
    error_msg: str,
) -> None:
    """Records `last_error` for a provider without putting it in quota cooldown."""
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO provider_state (name, resting_until, last_error)
            VALUES (?, NULL, ?)
            ON CONFLICT(name) DO UPDATE SET
                last_error = excluded.last_error
            """,
            (provider_name, error_msg[:500]),
        )


def clear_provider_rest(db_file: Path, provider_name: str) -> None:
    """Clears cooldown and error state for `provider_name` after a successful call."""
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO provider_state (name, resting_until, last_error)
            VALUES (?, NULL, NULL)
            ON CONFLICT(name) DO UPDATE SET
                resting_until = NULL,
                last_error = NULL
            """,
            (provider_name,),
        )


def earliest_recovery_seconds(
    db_file: Path,
    provider_names: list[str],
    *,
    now_ts: int | None = None,
    default_s: int = 3600,
) -> int:
    """Returns seconds until the earliest resting provider in `provider_names` recovers."""
    if not provider_names:
        return default_s
    current = int(now_ts if now_ts is not None else time.time())
    placeholders = ",".join("?" for _ in provider_names)
    rows = query_all(
        db_file,
        f"SELECT resting_until FROM provider_state WHERE name IN ({placeholders}) AND resting_until IS NOT NULL",
        provider_names,
    )
    remaining: list[int] = []
    for r in rows:
        try:
            u = int(r["resting_until"])
            if u > current:
                remaining.append(u - current)
        except (ValueError, TypeError):
            continue
    return max(1, min(remaining)) if remaining else default_s
