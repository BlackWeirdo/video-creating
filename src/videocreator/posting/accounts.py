"""Connected social accounts: one `accounts` row and its access token in the secrets store."""
from __future__ import annotations

import hashlib
from typing import Literal

from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore


def upsert_account(
    paths: AppPaths,
    *,
    platform: Literal["facebook", "instagram", "threads", "tiktok"],
    external_id: str,
    name: str,
    access_token: str,
    lang: Literal["vi", "en"] = "vi",
    token_expires_at: str | None = None,
    secrets_store: SecretsStore | None = None,
) -> int:
    clean_ext = external_id.strip()
    clean_name = name.strip() or f"{platform}:{clean_ext}"
    if not clean_ext:
        raise ValueError("Account external_id is required")

    sec = secrets_store or SecretsStore(paths.secrets_file)
    secret_key = f"ACCOUNT_TOKEN_{platform.upper()}_{hashlib.md5(clean_ext.encode('utf-8')).hexdigest()[:10]}"
    if access_token.strip():
        sec.set(secret_key, access_token.strip())

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO accounts (
                platform, external_id, name, lang, secret_key, token_expires_at, enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(platform, external_id) DO UPDATE SET
                name = excluded.name,
                lang = excluded.lang,
                secret_key = excluded.secret_key,
                token_expires_at = COALESCE(excluded.token_expires_at, accounts.token_expires_at),
                enabled = 1
            """,
            (platform, clean_ext, clean_name, lang, secret_key, token_expires_at),
        )
        row = conn.execute(
            "SELECT id FROM accounts WHERE platform = ? AND external_id = ?",
            (platform, clean_ext),
        ).fetchone()
        acc_id = int(row["id"]) if row else 0
        record_audit(
            conn,
            actor="ui",
            action="account.upserted",
            object_type="account",
            object_id=acc_id,
            detail=f"{platform}:{clean_name} ({clean_ext})",
        )
        return acc_id
