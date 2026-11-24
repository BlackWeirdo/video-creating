"""Video Style Preset CRUD and validation helpers (Phase 02, V2-STY-01..05)."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from videocreator.db import get_write_conn, query_all, query_one, record_audit

SUBTITLE_STYLES: tuple[str, ...] = (
    "karaoke_highlight",
    "tiktok_pop",
    "box_highlight",
    "neon_glow",
    "minimal_bottom",
    "bilingual",
)
SUBTITLE_POSITIONS: tuple[str, ...] = ("bottom", "center", "top")
MOTION_PRESETS: tuple[str, ...] = ("none", "subtle_zoom")
DEFAULT_STYLE_PRESET_ID = "tiktok_karaoke"

_SLUG_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,47}$")
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _clean_hex(value: str | None, default: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return default
    if not _HEX_COLOR_RE.match(raw):
        raise ValueError(f"Invalid hex color '{raw}'; expected #RRGGBB or #AARRGGBB")
    return raw.upper()


def _parse_preset_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "workspace_id": int(row["workspace_id"]) if row.get("workspace_id") is not None else None,
        "name": str(row["name"]),
        "subtitle_style": str(row.get("subtitle_style") or "karaoke_highlight"),
        "font_name": str(row.get("font_name") or "Be Vietnam Pro"),
        "font_size": int(row.get("font_size") or 58),
        "primary_color": str(row.get("primary_color") or "#FFFFFF"),
        "highlight_color": str(row.get("highlight_color") or "#FFE082"),
        "outline_color": str(row.get("outline_color") or "#141414"),
        "box_color": str(row.get("box_color") or "#99121216"),
        "position": str(row.get("position") or "bottom"),
        "ducking_enabled": bool(row.get("ducking_enabled", 1)),
        "music_volume": float(row.get("music_volume") if row.get("music_volume") is not None else 0.22),
        "sfx_transition_asset_id": (
            int(row["sfx_transition_asset_id"])
            if row.get("sfx_transition_asset_id") is not None
            else None
        ),
        "intro_text": str(row.get("intro_text") or ""),
        "outro_text": str(row.get("outro_text") or ""),
        "motion_preset": str(row.get("motion_preset") or "none"),
        "is_builtin": bool(row.get("is_builtin")),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _validate_preset_fields(
    *,
    subtitle_style: str | None = None,
    position: str | None = None,
    motion_preset: str | None = None,
    font_size: int | None = None,
    music_volume: float | None = None,
) -> None:
    if subtitle_style is not None and subtitle_style not in SUBTITLE_STYLES:
        raise ValueError(
            f"Invalid subtitle_style '{subtitle_style}'; expected one of {SUBTITLE_STYLES}"
        )
    if position is not None and position not in SUBTITLE_POSITIONS:
        raise ValueError(f"Invalid position '{position}'; expected one of {SUBTITLE_POSITIONS}")
    if motion_preset is not None and motion_preset not in MOTION_PRESETS:
        raise ValueError(
            f"Invalid motion_preset '{motion_preset}'; expected one of {MOTION_PRESETS}"
        )
    if font_size is not None and not (24 <= int(font_size) <= 120):
        raise ValueError("font_size must be between 24 and 120")
    if music_volume is not None and not (0.0 <= float(music_volume) <= 1.0):
        raise ValueError("music_volume must be between 0.0 and 1.0")


def list_style_presets(
    db_file: Path, *, workspace_id: int | None = None
) -> list[dict[str, Any]]:
    if workspace_id is not None:
        rows = query_all(
            db_file,
            """
            SELECT * FROM style_presets
            WHERE workspace_id IS NULL OR workspace_id = ?
            ORDER BY is_builtin DESC, created_at ASC, id ASC
            """,
            (int(workspace_id),),
        )
    else:
        rows = query_all(
            db_file,
            "SELECT * FROM style_presets ORDER BY is_builtin DESC, created_at ASC, id ASC",
        )
    return [_parse_preset_row(r) for r in rows]


def get_style_preset(db_file: Path, preset_id: str) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM style_presets WHERE id = ?", (preset_id.strip(),))
    return _parse_preset_row(row) if row is not None else None


def resolve_style_preset(db_file: Path, preset_id: str | None) -> dict[str, Any]:
    """Resolves `preset_id`, falling back to `tiktok_karaoke` or an in-memory default."""
    candidate = (preset_id or "").strip() or DEFAULT_STYLE_PRESET_ID
    found = get_style_preset(db_file, candidate)
    if found is not None:
        return found
    fallback = get_style_preset(db_file, DEFAULT_STYLE_PRESET_ID)
    if fallback is not None:
        return fallback
    return {
        "id": DEFAULT_STYLE_PRESET_ID,
        "workspace_id": None,
        "name": "TikTok Karaoke Tô Chữ",
        "subtitle_style": "karaoke_highlight",
        "font_name": "Be Vietnam Pro",
        "font_size": 58,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFE082",
        "outline_color": "#141414",
        "box_color": "#99121216",
        "position": "bottom",
        "ducking_enabled": True,
        "music_volume": 0.22,
        "sfx_transition_asset_id": None,
        "intro_text": "",
        "outro_text": "",
        "motion_preset": "none",
        "is_builtin": True,
    }


def create_style_preset(
    db_file: Path,
    *,
    name: str,
    preset_id: str = "",
    workspace_id: int | None = None,
    subtitle_style: str = "karaoke_highlight",
    font_name: str = "Be Vietnam Pro",
    font_size: int = 58,
    primary_color: str = "#FFFFFF",
    highlight_color: str = "#FFE082",
    outline_color: str = "#141414",
    box_color: str = "#99121216",
    position: str = "bottom",
    ducking_enabled: bool = True,
    music_volume: float = 0.22,
    sfx_transition_asset_id: int | None = None,
    intro_text: str = "",
    outro_text: str = "",
    motion_preset: str = "none",
    actor: str = "ui",
) -> dict[str, Any]:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Style preset name is required")
    _validate_preset_fields(
        subtitle_style=subtitle_style,
        position=position,
        motion_preset=motion_preset,
        font_size=font_size,
        music_volume=music_volume,
    )
    clean_primary = _clean_hex(primary_color, "#FFFFFF")
    clean_highlight = _clean_hex(highlight_color, "#FFE082")
    clean_outline = _clean_hex(outline_color, "#141414")
    clean_box = _clean_hex(box_color, "#99121216")

    pid = preset_id.strip().lower()
    if pid:
        if not _SLUG_ID_RE.match(pid):
            raise ValueError("Preset id must use lowercase ASCII letters, digits, hyphens, or underscores")
        if get_style_preset(db_file, pid) is not None:
            raise ValueError(f"Style preset '{pid}' already exists")
    else:
        slug_base = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-")[:32] or "style"
        pid = f"{slug_base}-{uuid.uuid4().hex[:6]}"

    with get_write_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO style_presets (
                id, workspace_id, name, subtitle_style, font_name, font_size,
                primary_color, highlight_color, outline_color, box_color,
                position, ducking_enabled, music_volume, sfx_transition_asset_id,
                intro_text, outro_text, motion_preset, is_builtin
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                pid,
                int(workspace_id) if workspace_id is not None else None,
                clean_name,
                subtitle_style,
                font_name.strip() or "Be Vietnam Pro",
                int(font_size),
                clean_primary,
                clean_highlight,
                clean_outline,
                clean_box,
                position,
                1 if ducking_enabled else 0,
                round(float(music_volume), 3),
                int(sfx_transition_asset_id) if sfx_transition_asset_id is not None else None,
                intro_text.strip(),
                outro_text.strip(),
                motion_preset,
            ),
        )
        record_audit(
            conn,
            actor=actor,
            action="style_preset.created",
            object_type="style_preset",
            detail=f"{pid} ({subtitle_style})",
        )
    created = get_style_preset(db_file, pid)
    assert created is not None
    return created


def update_style_preset(
    db_file: Path,
    preset_id: str,
    *,
    name: str | None = None,
    subtitle_style: str | None = None,
    font_name: str | None = None,
    font_size: int | None = None,
    primary_color: str | None = None,
    highlight_color: str | None = None,
    outline_color: str | None = None,
    box_color: str | None = None,
    position: str | None = None,
    ducking_enabled: bool | None = None,
    music_volume: float | None = None,
    sfx_transition_asset_id: int | None = None,
    clear_sfx: bool = False,
    intro_text: str | None = None,
    outro_text: str | None = None,
    motion_preset: str | None = None,
    actor: str = "ui",
) -> dict[str, Any]:
    existing = get_style_preset(db_file, preset_id)
    if existing is None:
        raise LookupError(f"Style preset '{preset_id}' not found")
    _validate_preset_fields(
        subtitle_style=subtitle_style,
        position=position,
        motion_preset=motion_preset,
        font_size=font_size,
        music_volume=music_volume,
    )

    next_name = name.strip() if name is not None else existing["name"]
    if not next_name:
        raise ValueError("Style preset name cannot be empty")
    next_sfx = None if clear_sfx else (
        int(sfx_transition_asset_id)
        if sfx_transition_asset_id is not None
        else existing["sfx_transition_asset_id"]
    )

    with get_write_conn(db_file) as conn:
        conn.execute(
            """
            UPDATE style_presets
            SET name = ?,
                subtitle_style = ?,
                font_name = ?,
                font_size = ?,
                primary_color = ?,
                highlight_color = ?,
                outline_color = ?,
                box_color = ?,
                position = ?,
                ducking_enabled = ?,
                music_volume = ?,
                sfx_transition_asset_id = ?,
                intro_text = ?,
                outro_text = ?,
                motion_preset = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (
                next_name,
                subtitle_style or existing["subtitle_style"],
                font_name.strip() if font_name is not None else existing["font_name"],
                int(font_size) if font_size is not None else existing["font_size"],
                _clean_hex(primary_color, existing["primary_color"])
                if primary_color is not None
                else existing["primary_color"],
                _clean_hex(highlight_color, existing["highlight_color"])
                if highlight_color is not None
                else existing["highlight_color"],
                _clean_hex(outline_color, existing["outline_color"])
                if outline_color is not None
                else existing["outline_color"],
                _clean_hex(box_color, existing["box_color"])
                if box_color is not None
                else existing["box_color"],
                position or existing["position"],
                int(ducking_enabled) if ducking_enabled is not None else int(existing["ducking_enabled"]),
                round(float(music_volume), 3)
                if music_volume is not None
                else existing["music_volume"],
                next_sfx,
                intro_text.strip() if intro_text is not None else existing["intro_text"],
                outro_text.strip() if outro_text is not None else existing["outro_text"],
                motion_preset or existing["motion_preset"],
                existing["id"],
            ),
        )
        record_audit(
            conn,
            actor=actor,
            action="style_preset.updated",
            object_type="style_preset",
            detail=existing["id"],
        )
    updated = get_style_preset(db_file, existing["id"])
    assert updated is not None
    return updated


def delete_style_preset(
    db_file: Path, preset_id: str, *, actor: str = "ui"
) -> None:
    existing = get_style_preset(db_file, preset_id)
    if existing is None:
        raise LookupError(f"Style preset '{preset_id}' not found")
    if existing["is_builtin"]:
        raise ValueError(f"Cannot delete built-in style preset '{preset_id}'")
    with get_write_conn(db_file) as conn:
        conn.execute("DELETE FROM style_presets WHERE id = ?", (existing["id"],))
        record_audit(
            conn,
            actor=actor,
            action="style_preset.deleted",
            object_type="style_preset",
            detail=existing["id"],
        )
