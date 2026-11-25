"""SQLite database connection, migrations (via PRAGMA user_version), and query helpers."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from videocreator.paths import PACKAGE_DIR

DEFAULT_MIGRATIONS_DIR = PACKAGE_DIR / "migrations"


def connect(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


@contextmanager
def get_conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_file)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_write_conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    """Opens a write transaction with `BEGIN IMMEDIATE` so read-then-write updates
    wait on `busy_timeout` instead of failing with `SQLITE_BUSY_SNAPSHOT` under WAL."""
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_file), timeout=5.0, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


def get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version;").fetchone()
    return int(row[0]) if row else 0


def _migration_version(sql_file: Path, fallback_idx: int) -> int:
    prefix = sql_file.stem.split("_", 1)[0]
    return int(prefix) if prefix.isdigit() else fallback_idx


def max_supported_migration_version(migrations_dir: Path | None = None) -> int:
    mig_dir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    sql_files = sorted(mig_dir.glob("*.sql"), key=lambda p: p.name)
    if not sql_files:
        return 0
    return max(_migration_version(f, idx) for idx, f in enumerate(sql_files, start=1))


def _strip_explicit_tx(script: str) -> str:
    """Removes top-level BEGIN;/COMMIT; lines so `migrate()` controls a single transaction."""
    out: list[str] = []
    for line in script.splitlines():
        token = line.strip().rstrip(";").upper()
        if token in ("BEGIN", "BEGIN TRANSACTION", "BEGIN IMMEDIATE", "COMMIT", "END"):
            continue
        out.append(line)
    return "\n".join(out)


def migrate(db_file: Path, migrations_dir: Path | None = None) -> int:
    mig_dir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    sql_files = sorted(mig_dir.glob("*.sql"), key=lambda p: p.name)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_file), timeout=5.0, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        current = get_user_version(conn)
        for idx, sql_file in enumerate(sql_files, start=1):
            ver = _migration_version(sql_file, idx)
            if ver <= current:
                continue
            raw_sql = sql_file.read_text(encoding="utf-8")
            needs_fk_off = "-- pragma: foreign_keys=off" in raw_sql.lower()
            body = _strip_explicit_tx(raw_sql)
            if needs_fk_off:
                conn.execute("PRAGMA foreign_keys = OFF;")
            try:
                conn.executescript(
                    f"BEGIN IMMEDIATE;\n{body}\nPRAGMA user_version = {ver};\nCOMMIT;"
                )
                if needs_fk_off:
                    fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
                    if fk_violations:
                        raise RuntimeError(
                            f"Foreign key check failed after {sql_file.name}: {[dict(r) for r in fk_violations]}"
                        )
            finally:
                conn.execute("PRAGMA foreign_keys = ON;")
            current = ver
        return current
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


def query_all(
    db_file: Path, sql: str, params: tuple[Any, ...] | list[Any] = ()
) -> list[dict[str, Any]]:
    with get_conn(db_file) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def query_one(
    db_file: Path, sql: str, params: tuple[Any, ...] | list[Any] = ()
) -> dict[str, Any] | None:
    with get_conn(db_file) as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None


def execute(
    db_file: Path, sql: str, params: tuple[Any, ...] | list[Any] = ()
) -> int:
    with get_conn(db_file) as conn:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid or 0)


def record_audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    object_type: str,
    object_id: int | None = None,
    detail: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (actor, action, object_type, object_id, detail)
        VALUES (?, ?, ?, ?, ?)
        """,
        (actor, action, object_type, object_id, detail),
    )


def get_setting(db_file: Path, key: str, default: str | None = None) -> str | None:
    row = query_one(db_file, "SELECT value FROM settings WHERE key = ?", (key,))
    if row is None or row.get("value") is None:
        return default
    return str(row["value"])


def set_setting(db_file: Path, key: str, value: str) -> None:
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

