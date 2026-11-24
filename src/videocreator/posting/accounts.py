"""Connected social accounts: one `accounts` row and its access token in the secrets store."""
from __future__ import annotations

import hashlib
from typing import Literal

from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.workspaces import DEFAULT_WORKSPACE_ID, require_workspace

ACCOUNT_APPROVAL_MODES: tuple[str, ...] = ("inherit", "single", "bulk", "autopilot")


def upsert_account(
    paths: AppPaths,
    *,
    platform: Literal["facebook", "instagram", "threads", "tiktok", "youtube"],
    external_id: str,
    name: str,
    access_token: str,
    lang: Literal["vi", "en"] = "vi",
    token_expires_at: str | None = None,
    workspace_id: int = DEFAULT_WORKSPACE_ID,
    approval_mode: str = "inherit",
    autopilot_min_score: float = 8.0,
    channel_group: str = "",
    secrets_store: SecretsStore | None = None,
) -> int:
    clean_ext = external_id.strip()
    clean_name = name.strip() or f"{platform}:{clean_ext}"
    if not clean_ext:
        raise ValueError("Account external_id is required")
    clean_mode = (approval_mode or "inherit").strip()
    if clean_mode not in ACCOUNT_APPROVAL_MODES:
        raise ValueError(f"Invalid account approval_mode '{clean_mode}'")
    ws = require_workspace(paths.db_file, int(workspace_id))

    sec = secrets_store or SecretsStore(paths.secrets_file)
    secret_key = f"ACCOUNT_TOKEN_{platform.upper()}_{hashlib.md5(clean_ext.encode('utf-8')).hexdigest()[:10]}"
    if access_token.strip():
        sec.set(secret_key, access_token.strip())

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO accounts (
                platform, external_id, name, lang, secret_key, token_expires_at,
                enabled, workspace_id, approval_mode, autopilot_min_score, channel_group
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(platform, external_id) DO UPDATE SET
                name = excluded.name,
                lang = excluded.lang,
                secret_key = excluded.secret_key,
                token_expires_at = COALESCE(excluded.token_expires_at, accounts.token_expires_at),
                enabled = 1,
                workspace_id = excluded.workspace_id,
                approval_mode = excluded.approval_mode,
                autopilot_min_score = excluded.autopilot_min_score,
                channel_group = excluded.channel_group
            """,
            (
                platform,
                clean_ext,
                clean_name,
                lang,
                secret_key,
                token_expires_at,
                int(ws["id"]),
                clean_mode,
                float(autopilot_min_score),
                channel_group.strip(),
            ),
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
            detail=f"{platform}:{clean_name} (ws={ws['id']}, ext={clean_ext})",
        )
        return acc_id
