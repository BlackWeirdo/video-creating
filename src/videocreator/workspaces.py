"""Multi-workspace (brand/channel-group) management and isolation helpers."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from videocreator.db import (
    get_conn,
    get_setting,
    get_write_conn,
    query_all,
    query_one,
    record_audit,
    set_setting,
)
from videocreator.jsonutil import loads_or

CONTENT_POLICIES: tuple[str, ...] = ("strict_footage", "hybrid_remix", "full_ai")
APPROVAL_MODES: tuple[str, ...] = ("single", "bulk", "autopilot")
ASPECT_RATIOS: tuple[str, ...] = ("9:16", "16:9", "1:1")
DEFAULT_WORKSPACE_ID = 1
ACTIVE_WORKSPACE_SETTING_KEY = "active_workspace_id"
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _slugify(text: str) -> str:
    normalized = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", normalized)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug[:48].strip("-") or "workspace"


def _parse_workspace_row(row: dict[str, Any]) -> dict[str, Any]:
    raw_settings = loads_or(row.get("settings_json"), {})
    if not isinstance(raw_settings, dict):
        raw_settings = {}
    return {
        "id": int(row["id"]),
        "slug": str(row["slug"]),
        "name": str(row["name"]),
        "niche": str(row.get("niche") or "general"),
        "content_policy": str(row.get("content_policy") or "strict_footage"),
        "approval_mode": str(row.get("approval_mode") or "single"),
        "default_aspect_ratio": str(row.get("default_aspect_ratio") or "9:16"),
        "style_preset": str(row.get("style_preset") or "tiktok_karaoke"),
        "tg_chat_id": str(row.get("tg_chat_id") or ""),
        "tg_bot_secret_key": str(row.get("tg_bot_secret_key") or ""),
        "settings": raw_settings,
        "archived": bool(row.get("archived")),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _validate_policy_fields(
    *,
    content_policy: str | None = None,
    approval_mode: str | None = None,
    default_aspect_ratio: str | None = None,
) -> None:
    if content_policy is not None and content_policy not in CONTENT_POLICIES:
        raise ValueError(
            f"Invalid content_policy '{content_policy}'; expected one of {CONTENT_POLICIES}"
        )
    if approval_mode is not None and approval_mode not in APPROVAL_MODES:
        raise ValueError(
            f"Invalid approval_mode '{approval_mode}'; expected one of {APPROVAL_MODES}"
        )
    if default_aspect_ratio is not None and default_aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(
            f"Invalid default_aspect_ratio '{default_aspect_ratio}'; expected one of {ASPECT_RATIOS}"
        )


def list_workspaces(
    db_file: Path, *, include_archived: bool = False
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM workspaces"
    if not include_archived:
        sql += " WHERE archived = 0"
    sql += " ORDER BY id ASC"
    return [_parse_workspace_row(r) for r in query_all(db_file, sql)]


def get_workspace(db_file: Path, workspace_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
    return _parse_workspace_row(row) if row is not None else None


def get_workspace_by_slug(db_file: Path, slug: str) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM workspaces WHERE slug = ?", (slug.strip(),))
    return _parse_workspace_row(row) if row is not None else None


def require_workspace(db_file: Path, workspace_id: int) -> dict[str, Any]:
    """Ensures `workspace_id` exists and is active, enforcing workspace FK integrity."""
    ws = get_workspace(db_file, workspace_id)
    if ws is None:
        raise LookupError(f"Workspace {workspace_id} not found")
    if ws["archived"]:
        raise ValueError(f"Workspace {workspace_id} is archived")
    return ws


def _unique_slug(db_file: Path, base_slug: str) -> str:
    candidate = base_slug
    suffix = 2
    while get_workspace_by_slug(db_file, candidate) is not None:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    return candidate


def create_workspace(
    db_file: Path,
    *,
    name: str,
    slug: str = "",
    niche: str = "general",
    content_policy: str = "strict_footage",
    approval_mode: str = "single",
    default_aspect_ratio: str = "9:16",
    style_preset: str = "tiktok_karaoke",
    tg_chat_id: str = "",
    tg_bot_secret_key: str = "",
    settings: dict[str, Any] | None = None,
    actor: str = "ui",
) -> int:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Workspace name is required")
    _validate_policy_fields(
        content_policy=content_policy,
        approval_mode=approval_mode,
        default_aspect_ratio=default_aspect_ratio,
    )

    clean_slug = slug.strip().lower()
    if clean_slug:
        if not _SLUG_RE.match(clean_slug):
            raise ValueError(
                "Workspace slug must use lowercase ASCII letters, digits, and hyphens"
            )
        if get_workspace_by_slug(db_file, clean_slug) is not None:
            raise ValueError(f"Workspace slug '{clean_slug}' already exists")
    else:
        clean_slug = _unique_slug(db_file, _slugify(clean_name))

    settings_json = json.dumps(settings or {}, ensure_ascii=False)
    with get_write_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO workspaces (
                slug, name, niche, content_policy, approval_mode,
                default_aspect_ratio, style_preset, tg_chat_id,
                tg_bot_secret_key, settings_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_slug,
                clean_name,
                niche.strip() or "general",
                content_policy,
                approval_mode,
                default_aspect_ratio,
                style_preset.strip() or "tiktok_karaoke",
                tg_chat_id.strip(),
                tg_bot_secret_key.strip(),
                settings_json,
            ),
        )
        new_id = int(cur.lastrowid or 0)
        record_audit(
            conn,
            actor=actor,
            action="workspace.created",
            object_type="workspace",
            object_id=new_id,
            detail=f"{clean_slug} ({content_policy}/{approval_mode})",
        )
    return new_id


def update_workspace(
    db_file: Path,
    workspace_id: int,
    *,
    name: str | None = None,
    niche: str | None = None,
    content_policy: str | None = None,
    approval_mode: str | None = None,
    default_aspect_ratio: str | None = None,
    style_preset: str | None = None,
    tg_chat_id: str | None = None,
    tg_bot_secret_key: str | None = None,
    settings: dict[str, Any] | None = None,
    actor: str = "ui",
) -> dict[str, Any]:
    existing = get_workspace(db_file, workspace_id)
    if existing is None:
        raise LookupError(f"Workspace {workspace_id} not found")
    _validate_policy_fields(
        content_policy=content_policy,
        approval_mode=approval_mode,
        default_aspect_ratio=default_aspect_ratio,
    )

    next_name = existing["name"] if name is None else name.strip()
    if not next_name:
        raise ValueError("Workspace name is required")
    next_niche = existing["niche"] if niche is None else (niche.strip() or "general")
    next_policy = existing["content_policy"] if content_policy is None else content_policy
    next_approval = existing["approval_mode"] if approval_mode is None else approval_mode
    next_ratio = (
        existing["default_aspect_ratio"]
        if default_aspect_ratio is None
        else default_aspect_ratio
    )
    next_style = (
        existing["style_preset"]
        if style_preset is None
        else (style_preset.strip() or "tiktok_karaoke")
    )
    next_tg_chat = existing["tg_chat_id"] if tg_chat_id is None else tg_chat_id.strip()
    next_tg_secret = (
        existing["tg_bot_secret_key"]
        if tg_bot_secret_key is None
        else tg_bot_secret_key.strip()
    )
    next_settings = existing["settings"] if settings is None else settings

    with get_write_conn(db_file) as conn:
        conn.execute(
            """
            UPDATE workspaces
            SET name = ?,
                niche = ?,
                content_policy = ?,
                approval_mode = ?,
                default_aspect_ratio = ?,
                style_preset = ?,
                tg_chat_id = ?,
                tg_bot_secret_key = ?,
                settings_json = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (
                next_name,
                next_niche,
                next_policy,
                next_approval,
                next_ratio,
                next_style,
                next_tg_chat,
                next_tg_secret,
                json.dumps(next_settings, ensure_ascii=False),
                workspace_id,
            ),
        )
        record_audit(
            conn,
            actor=actor,
            action="workspace.updated",
            object_type="workspace",
            object_id=workspace_id,
            detail=f"{existing['slug']} ({next_policy}/{next_approval})",
        )
    updated = get_workspace(db_file, workspace_id)
    assert updated is not None
    return updated


def archive_workspace(
    db_file: Path, workspace_id: int, *, actor: str = "ui"
) -> dict[str, Any]:
    if workspace_id == DEFAULT_WORKSPACE_ID:
        raise ValueError("Cannot archive the default workspace")
    existing = get_workspace(db_file, workspace_id)
    if existing is None:
        raise LookupError(f"Workspace {workspace_id} not found")
    if existing["archived"]:
        return existing

    active = list_workspaces(db_file, include_archived=False)
    if len(active) <= 1:
        raise ValueError("Cannot archive the last active workspace")

    with get_write_conn(db_file) as conn:
        conn.execute(
            """
            UPDATE workspaces
            SET archived = 1,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (workspace_id,),
        )
        record_audit(
            conn,
            actor=actor,
            action="workspace.archived",
            object_type="workspace",
            object_id=workspace_id,
            detail=existing["slug"],
        )

    if get_active_workspace_id(db_file) == workspace_id:
        set_setting(db_file, ACTIVE_WORKSPACE_SETTING_KEY, str(DEFAULT_WORKSPACE_ID))

    archived = get_workspace(db_file, workspace_id)
    assert archived is not None
    return archived


def get_active_workspace_id(db_file: Path) -> int:
    raw = get_setting(db_file, ACTIVE_WORKSPACE_SETTING_KEY)
    if raw and raw.isdigit():
        ws = get_workspace(db_file, int(raw))
        if ws is not None and not ws["archived"]:
            return int(ws["id"])
    return DEFAULT_WORKSPACE_ID


def set_active_workspace_id(
    db_file: Path, workspace_id: int, *, actor: str = "ui"
) -> int:
    ws = require_workspace(db_file, workspace_id)
    set_setting(db_file, ACTIVE_WORKSPACE_SETTING_KEY, str(ws["id"]))
    with get_conn(db_file) as conn:
        record_audit(
            conn,
            actor=actor,
            action="workspace.activated",
            object_type="workspace",
            object_id=int(ws["id"]),
            detail=ws["slug"],
        )
    return int(ws["id"])
