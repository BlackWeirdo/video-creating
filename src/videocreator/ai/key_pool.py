"""Encrypted multi-key API rotation pool with quota cooldown failover (Phase 06)."""
from __future__ import annotations

import secrets as _secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore

POOL_PROVIDERS: frozenset[str] = frozenset(
    {"gemini", "claude", "openai_compat", "fal", "elevenlabs", "muse"}
)


def mask_secret_value(raw: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= 8:
        return "*" * len(cleaned)
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def _resolve_db_and_secrets(
    target: AppPaths | Path,
    secrets_store: SecretsStore | None = None,
) -> tuple[Path, SecretsStore]:
    if isinstance(target, AppPaths):
        return target.db_file, secrets_store or SecretsStore(target.secrets_file)
    db_file = Path(target)
    if secrets_store is not None:
        return db_file, secrets_store
    return db_file, SecretsStore(db_file.parent / "secrets.bin")


def _utc_iso_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, seconds))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _format_pool_row(row: dict[str, Any], secrets: SecretsStore) -> dict[str, Any]:
    raw_val = secrets.get(str(row["secret_key"])) or ""
    cooldown_until = str(row.get("cooldown_until") or "")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": int(row["id"]),
        "provider": str(row["provider"]),
        "label": str(row.get("label") or ""),
        "secret_key": str(row["secret_key"]),
        "configured": bool(raw_val),
        "masked_preview": mask_secret_value(raw_val),
        "enabled": bool(row.get("enabled", 1)),
        "priority": int(row.get("priority") or 0),
        "cooldown_until": cooldown_until,
        "is_cooling_down": bool(cooldown_until and cooldown_until > now_iso),
        "use_count": int(row.get("use_count") or 0),
        "fail_count": int(row.get("fail_count") or 0),
        "last_used_at": str(row.get("last_used_at") or ""),
        "last_error": row.get("last_error"),
        "created_at": str(row.get("created_at") or ""),
    }


def list_pooled_keys(
    paths: AppPaths,
    *,
    provider: str | None = None,
    secrets_store: SecretsStore | None = None,
) -> list[dict[str, Any]]:
    secrets = secrets_store or SecretsStore(paths.secrets_file)
    if provider:
        rows = query_all(
            paths.db_file,
            "SELECT * FROM api_key_pool WHERE provider = ? ORDER BY priority DESC, id ASC",
            (provider,),
        )
    else:
        rows = query_all(
            paths.db_file,
            "SELECT * FROM api_key_pool ORDER BY provider ASC, priority DESC, id ASC",
        )
    return [_format_pool_row(r, secrets) for r in rows]


def add_pooled_key(
    paths: AppPaths,
    *,
    provider: str,
    raw_secret: str,
    label: str = "",
    priority: int = 0,
    secrets_store: SecretsStore | None = None,
) -> dict[str, Any]:
    clean_provider = (provider or "").strip().lower()
    if clean_provider not in POOL_PROVIDERS:
        raise ValueError(f"Unsupported key pool provider '{provider}'")
    cleaned_secret = (raw_secret or "").strip()
    if not cleaned_secret:
        raise ValueError("API key secret value cannot be empty")

    secrets = secrets_store or SecretsStore(paths.secrets_file)
    placeholder_key = f"POOL_{clean_provider.upper()}_{_secrets.token_hex(8)}"
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO api_key_pool (provider, label, secret_key, enabled, priority)
            VALUES (?, ?, ?, 1, ?)
            """,
            (clean_provider, label.strip(), placeholder_key, int(priority)),
        )
        key_id = int(cur.lastrowid)
        final_secret_key = f"POOL_{clean_provider.upper()}_{key_id}"
        conn.execute(
            "UPDATE api_key_pool SET secret_key = ? WHERE id = ?",
            (final_secret_key, key_id),
        )
        secrets.set(final_secret_key, cleaned_secret)
        record_audit(
            conn,
            actor="key_pool",
            action="add_key",
            object_type="api_key_pool",
            object_id=key_id,
            detail=f"{clean_provider} ({label.strip() or final_secret_key})",
        )
    row = query_one(paths.db_file, "SELECT * FROM api_key_pool WHERE id = ?", (key_id,))
    assert row is not None
    return _format_pool_row(row, secrets)


def update_pooled_key(
    paths: AppPaths,
    key_id: int,
    *,
    label: str | None = None,
    enabled: bool | None = None,
    priority: int | None = None,
    clear_cooldown: bool = False,
    secrets_store: SecretsStore | None = None,
) -> dict[str, Any] | None:
    row = query_one(paths.db_file, "SELECT * FROM api_key_pool WHERE id = ?", (int(key_id),))
    if row is None:
        return None
    sets: list[str] = []
    params: list[Any] = []
    if label is not None:
        sets.append("label = ?")
        params.append(label.strip())
    if enabled is not None:
        sets.append("enabled = ?")
        params.append(1 if enabled else 0)
    if priority is not None:
        sets.append("priority = ?")
        params.append(int(priority))
    if clear_cooldown:
        sets.append("cooldown_until = ''")
        sets.append("last_error = NULL")
    if sets:
        params.append(int(key_id))
        with get_conn(paths.db_file) as conn:
            conn.execute(
                f"UPDATE api_key_pool SET {', '.join(sets)} WHERE id = ?",
                params,
            )
    secrets = secrets_store or SecretsStore(paths.secrets_file)
    updated = query_one(paths.db_file, "SELECT * FROM api_key_pool WHERE id = ?", (int(key_id),))
    assert updated is not None
    return _format_pool_row(updated, secrets)


def delete_pooled_key(
    paths: AppPaths,
    key_id: int,
    *,
    secrets_store: SecretsStore | None = None,
) -> bool:
    row = query_one(paths.db_file, "SELECT secret_key FROM api_key_pool WHERE id = ?", (int(key_id),))
    if row is None:
        return False
    secrets = secrets_store or SecretsStore(paths.secrets_file)
    secrets.delete(str(row["secret_key"]))
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM api_key_pool WHERE id = ?", (int(key_id),))
        record_audit(
            conn,
            actor="key_pool",
            action="delete_key",
            object_type="api_key_pool",
            object_id=int(key_id),
        )
    return True


def acquire_api_key(
    target: AppPaths | Path,
    provider: str,
    *,
    legacy_secret_name: str | None = None,
    secrets_store: SecretsStore | None = None,
) -> tuple[str | None, int | None]:
    """Selects the next active pooled API key (round-robin + priority), falling back to legacy secret."""
    db_file, secrets = _resolve_db_and_secrets(target, secrets_store)
    clean_provider = (provider or "").strip().lower()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        rows = query_all(
            db_file,
            """
            SELECT id, secret_key
            FROM api_key_pool
            WHERE provider = ?
              AND enabled = 1
              AND (cooldown_until = '' OR cooldown_until <= ?)
            ORDER BY priority DESC, use_count ASC, COALESCE(last_used_at, '') ASC, id ASC
            """,
            (clean_provider, now_iso),
        )
    except Exception:
        rows = []

    for r in rows:
        secret_val = (secrets.get(str(r["secret_key"])) or "").strip()
        if not secret_val:
            continue
        key_id = int(r["id"])
        with get_conn(db_file) as conn:
            conn.execute(
                """
                UPDATE api_key_pool
                SET use_count = use_count + 1,
                    last_used_at = ?,
                    cooldown_until = ''
                WHERE id = ?
                """,
                (now_iso, key_id),
            )
        return secret_val, key_id

    if legacy_secret_name:
        fallback = (secrets.get(legacy_secret_name) or "").strip()
        if fallback:
            return fallback, None
    return None, None


def mark_pooled_key_cooldown(
    db_file: Path,
    key_id: int | None,
    error_msg: str,
    *,
    cooldown_s: int = 900,
) -> None:
    if key_id is None:
        return
    until = _utc_iso_after(cooldown_s)
    with get_conn(db_file) as conn:
        conn.execute(
            """
            UPDATE api_key_pool
            SET fail_count = fail_count + 1,
                cooldown_until = ?,
                last_error = ?
            WHERE id = ?
            """,
            (until, (error_msg or "")[:300], int(key_id)),
        )


def mark_pooled_key_ok(db_file: Path, key_id: int | None) -> None:
    if key_id is None:
        return
    with get_conn(db_file) as conn:
        conn.execute(
            "UPDATE api_key_pool SET cooldown_until = '', last_error = NULL WHERE id = ?",
            (int(key_id),),
        )
