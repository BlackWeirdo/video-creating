"""Consistent Characters CRUD, reference image storage, and RGBA background cutout (V2-CHR-01..05)."""
from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import hydrate_row
from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths
from videocreator.pipeline.ai_images import (
    animate_image_to_shot,
    cutout_ai_image,
    generate_ai_image,
    get_ai_image,
    image_dims,
    list_ai_images,
)
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.characters")


def _hydrate_character(row: dict[str, Any]) -> dict[str, Any]:
    return hydrate_row(
        row,
        json_fields={
            "style_tags": ("style_tags_json", []),
            "cutout_simulation_flags": ("cutout_simulation_flags_json", []),
        },
    )


def create_character(
    paths: AppPaths,
    *,
    workspace_id: int,
    name: str,
    appearance_prompt: str = "",
    negative_prompt: str = "",
    seed: int | None = None,
    voice_id: str = "vi-VN-HoaiMyNeural",
    style_tags: list[str] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    require_workspace(paths.db_file, workspace_id)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Character name is required")
    locked_seed = int(seed) if seed is not None else (1000 + secrets.randbelow(900000))
    tags_json = json.dumps([str(t).strip() for t in (style_tags or []) if str(t).strip()], ensure_ascii=False)

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO characters (
                workspace_id, name, appearance_prompt, negative_prompt,
                seed, voice_id, style_tags_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_name,
                (appearance_prompt or "").strip(),
                (negative_prompt or "").strip(),
                locked_seed,
                (voice_id or "vi-VN-HoaiMyNeural").strip(),
                tags_json,
            ),
        )
        char_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_character",
            object_type="character",
            object_id=char_id,
            detail=f"{clean_name} (seed={locked_seed})",
        )
    ch = get_character(paths.db_file, char_id)
    assert ch is not None
    return ch


def list_characters(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM characters WHERE workspace_id = ? ORDER BY id DESC",
        (int(workspace_id),),
    )
    return [_hydrate_character(r) for r in rows]


def get_character(db_file: Path, character_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM characters WHERE id = ?", (int(character_id),))
    return _hydrate_character(row) if row else None


def update_character(
    paths: AppPaths,
    character_id: int,
    *,
    name: str | None = None,
    appearance_prompt: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
    voice_id: str | None = None,
    style_tags: list[str] | None = None,
) -> dict[str, Any] | None:
    if get_character(paths.db_file, character_id) is None:
        return None
    sets: list[str] = []
    params: list[Any] = []
    if name is not None and name.strip():
        sets.append("name = ?")
        params.append(name.strip())
    if appearance_prompt is not None:
        sets.append("appearance_prompt = ?")
        params.append(appearance_prompt.strip())
    if negative_prompt is not None:
        sets.append("negative_prompt = ?")
        params.append(negative_prompt.strip())
    if seed is not None:
        sets.append("seed = ?")
        params.append(int(seed))
    if voice_id is not None and voice_id.strip():
        sets.append("voice_id = ?")
        params.append(voice_id.strip())
    if style_tags is not None:
        sets.append("style_tags_json = ?")
        params.append(json.dumps([str(t).strip() for t in style_tags if str(t).strip()], ensure_ascii=False))
    if sets:
        params.append(int(character_id))
        with get_conn(paths.db_file) as conn:
            conn.execute(f"UPDATE characters SET {', '.join(sets)} WHERE id = ?", params)
    return get_character(paths.db_file, character_id)


def delete_character(paths: AppPaths, character_id: int) -> bool:
    if get_character(paths.db_file, character_id) is None:
        return False
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM characters WHERE id = ?", (int(character_id),))
        record_audit(
            conn,
            actor="characters",
            action="delete_character",
            object_type="character",
            object_id=int(character_id),
        )
    return True


def save_character_ref_image(
    paths: AppPaths,
    character_id: int,
    *,
    filename: str,
    data: bytes,
) -> dict[str, Any]:
    ch = get_character(paths.db_file, character_id)
    if ch is None:
        raise ValueError(f"Character #{character_id} not found")
    suffix = Path(filename or "ref.png").suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("Chỉ hỗ trợ ảnh tham chiếu .png / .jpg / .webp")
    dest_dir = paths.media_dir / "characters"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"char_{character_id}_ref{suffix}"
    dest.write_bytes(data)
    rel = f"characters/{dest.name}"
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE characters SET ref_image_path = ? WHERE id = ?",
            (rel, int(character_id)),
        )
    updated = get_character(paths.db_file, character_id)
    assert updated is not None
    return updated


def remove_background_with_flag(
    paths: AppPaths,
    src_image_path: Path,
    dst_png_path: Path,
    *,
    key_color: str = "0x111827",
) -> tuple[Path, bool]:
    """Removes image background via verified `rembg` (`u2net_custom`) on CPU, with tagged `colorkey` fallback."""
    import gc

    if not src_image_path.exists():
        raise FileNotFoundError(f"Source image missing: {src_image_path}")
    dst_png_path.parent.mkdir(parents=True, exist_ok=True)

    rembg_info = get_local_model(paths, "rembg_u2net")
    used_rembg = False
    if rembg_info and rembg_info.get("status") == "ready" and rembg_info.get("installed_on_disk"):
        try:
            from rembg import remove as rembg_remove
            from rembg.session_factory import new_session

            onnx_path = Path(str(rembg_info["local_path"]))
            if onnx_path.is_dir():
                onnx_path = next(onnx_path.glob("*.onnx"))
            sess = new_session(
                "u2net_custom",
                providers=["CPUExecutionProvider"],
                model_path=str(onnx_path),
            )
            try:
                out_bytes = rembg_remove(src_image_path.read_bytes(), session=sess)
                dst_png_path.write_bytes(out_bytes)
                used_rembg = True
            finally:
                del sess
                gc.collect()
        except Exception as exc:
            logger.warning("rembg u2net_custom failed for %s; using colorkey fallback: %s", src_image_path.name, exc)

    if not used_rembg:
        run_ffmpeg(
            [
                "-i",
                str(src_image_path.resolve()),
                "-vf",
                f"format=rgba,colorkey={key_color}:0.18:0.10",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                str(dst_png_path.resolve()),
            ],
            allow_creative_filters=True,
        )
    return dst_png_path, used_rembg


def remove_background_to_png(
    paths: AppPaths,
    src_image_path: Path,
    dst_png_path: Path,
    *,
    key_color: str = "0x111827",
) -> Path:
    """Removes image background using rembg (if ready & installed) or FFmpeg colorkey RGBA PNG."""
    out_path, _used = remove_background_with_flag(
        paths, src_image_path, dst_png_path, key_color=key_color
    )
    return out_path


def cutout_character(paths: AppPaths, character_id: int) -> dict[str, Any]:
    ch = get_character(paths.db_file, character_id)
    if ch is None:
        raise ValueError(f"Character #{character_id} not found")
    ref_rel = str(ch.get("ref_image_path") or "").strip()
    if not ref_rel:
        raise ValueError(f"Character #{character_id} has no reference image")
    src = paths.media_dir / ref_rel
    dst = paths.media_dir / "characters" / f"char_{character_id}_cutout.png"
    _, used_rembg = remove_background_with_flag(paths, src, dst)
    flags = [] if used_rembg else ["cutout_colorkey_fallback"]
    rel_cut = f"characters/{dst.name}"
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE characters SET cutout_image_path = ?, cutout_simulation_flags_json = ? WHERE id = ?",
            (rel_cut, json.dumps(flags), int(character_id)),
        )
    updated = get_character(paths.db_file, character_id)
    assert updated is not None
    return updated


__all__ = [
    "animate_image_to_shot",
    "create_character",
    "cutout_ai_image",
    "cutout_character",
    "delete_character",
    "generate_ai_image",
    "get_ai_image",
    "get_character",
    "image_dims",
    "list_ai_images",
    "list_characters",
    "remove_background_to_png",
    "remove_background_with_flag",
    "save_character_ref_image",
    "update_character",
]
