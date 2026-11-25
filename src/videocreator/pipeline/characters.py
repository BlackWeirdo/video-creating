"""Consistent Characters, AI Image Studio, RGBA cutout & Zoompan Motion Shots (V2-CHR-01..05)."""
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
from videocreator.pipeline.assembly import SEED_PALETTE, render_styled_still_png
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.characters")

_SEED_PALETTE = SEED_PALETTE


def _image_dims(aspect_ratio: str) -> tuple[int, int]:
    ratio = (aspect_ratio or "9:16").strip()
    if ratio == "16:9":
        return 960, 540
    if ratio == "1:1":
        return 720, 720
    return 540, 960


def _hydrate_character(row: dict[str, Any]) -> dict[str, Any]:
    return hydrate_row(
        row,
        json_fields={
            "style_tags": ("style_tags_json", []),
            "cutout_simulation_flags": ("cutout_simulation_flags_json", []),
        },
    )


def _hydrate_image(row: dict[str, Any]) -> dict[str, Any]:
    return hydrate_row(
        row,
        json_fields={"simulation_flags": ("simulation_flags_json", [])},
        bool_fields=("is_product_shot",),
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


_render_styled_still_png = render_styled_still_png


def animate_image_to_shot(
    paths: AppPaths,
    image_id: int,
    *,
    duration_s: float = 5.4,
) -> dict[str, Any]:
    """Animates an AI image PNG via FFmpeg `zoompan` into a reusable `shots` clip (`has_product=0`)."""
    row = query_one(paths.db_file, "SELECT * FROM ai_images WHERE id = ?", (int(image_id),))
    if row is None:
        raise ValueError(f"AI image #{image_id} not found")
    src_png = paths.media_dir / str(row["image_path"])
    if not src_png.exists():
        raise FileNotFoundError(f"AI image missing on disk: {src_png}")

    w, h = _image_dims(str(row.get("aspect_ratio") or "9:16"))
    dur = max(3.2, float(duration_s))
    frames = max(90, int(round(dur * 30)))

    rel_mp4 = f"assets/ai_img_{image_id}_motion.mp4"
    dest_mp4 = paths.media_dir / rel_mp4
    dest_mp4.parent.mkdir(parents=True, exist_ok=True)
    zp = (
        f"zoompan=z='min(zoom+0.0015,1.18)':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=30,format=yuv420p"
    )
    run_ffmpeg(
        [
            "-i",
            str(src_png.resolve()),
            "-vf",
            zp,
            "-t",
            f"{dur:.2f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(dest_mp4.resolve()),
        ],
        allow_creative_filters=True,
    )
    actual_dur = round(probe_duration(dest_mp4), 3)

    with get_conn(paths.db_file) as conn:
        a_id = int(
            conn.execute(
                "INSERT INTO assets (workspace_id, kind, path, duration_s, meta_json) VALUES (?, 'broll', ?, ?, ?)",
                (int(row["workspace_id"]), rel_mp4, actual_dur, json.dumps({"ai_image_id": image_id})),
            ).lastrowid
        )
        shot_id = int(
            conn.execute(
                """
                INSERT INTO shots (asset_id, idx, start_s, end_s, description, has_product, quality)
                VALUES (?, 0, 0.0, ?, ?, 0, 4)
                """,
                (a_id, actual_dur, str(row.get("prompt") or "AI Motion Scene")[:120]),
            ).lastrowid
        )
        conn.execute(
            "UPDATE ai_images SET motion_shot_id = ? WHERE id = ?",
            (shot_id, int(image_id)),
        )
    updated = get_ai_image(paths.db_file, image_id)
    assert updated is not None
    return updated


def get_ai_image(db_file: Path, image_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM ai_images WHERE id = ?", (int(image_id),))
    return _hydrate_image(row) if row else None


def list_ai_images(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM ai_images WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_image(r) for r in rows]


def generate_ai_image(
    paths: AppPaths,
    *,
    workspace_id: int,
    prompt: str,
    character_id: int | None = None,
    seed: int | None = None,
    aspect_ratio: str = "9:16",
    is_product_shot: bool = False,
    animate_to_shot: bool = True,
    actor: str = "api",
) -> dict[str, Any]:
    """Generates a consistent-character scene PNG (with BR-PRD-01 strict_footage product guard)."""
    ws = require_workspace(paths.db_file, workspace_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    if policy == "strict_footage" and is_product_shot:
        raise PermissionError(
            "Workspace 'strict_footage' cấm sinh ảnh sản phẩm bằng AI (`BR-PRD-01`); hãy dùng footage thật."
        )

    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        raise ValueError("Image prompt is required")

    ch = get_character(paths.db_file, character_id) if character_id else None
    if character_id and ch is None:
        raise ValueError(f"Character #{character_id} not found")

    locked_seed = int(seed) if seed is not None else (int(ch["seed"]) if ch else 1000 + secrets.randbelow(900000))
    merged_prompt = (
        f"[Character {ch['name']}: {ch['appearance_prompt']}] {clean_prompt}".strip()
        if ch and ch.get("appearance_prompt")
        else clean_prompt
    )
    ratio = (aspect_ratio or str(ws.get("default_aspect_ratio") or "9:16")).strip() or "9:16"
    w, h = _image_dims(ratio)

    overlay_path: Path | None = None
    if ch:
        cand_rel = str(ch.get("cutout_image_path") or ch.get("ref_image_path") or "").strip()
        if cand_rel and (paths.media_dir / cand_rel).exists():
            overlay_path = paths.media_dir / cand_rel

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO ai_images (
                workspace_id, character_id, prompt, seed, aspect_ratio,
                is_product_shot, provider, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'local_card', 'ready')
            """,
            (
                int(workspace_id),
                int(character_id) if character_id else None,
                merged_prompt,
                locked_seed,
                ratio,
                1 if is_product_shot else 0,
            ),
        )
        img_id = int(cur.lastrowid)

    rel_png = f"characters/ai_img_{img_id}.png"
    dest_png = paths.media_dir / rel_png
    _render_styled_still_png(dest_png, w=w, h=h, seed=locked_seed, overlay_image=overlay_path)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE ai_images SET image_path = ?, simulation_flags_json = ? WHERE id = ?",
            (rel_png, json.dumps(["ai_image_canvas_placeholder"]), img_id),
        )
        record_audit(
            conn,
            actor=actor,
            action="generate_ai_image",
            object_type="ai_image",
            object_id=img_id,
            detail=f"char={character_id} seed={locked_seed} ratio={ratio}",
        )

    if animate_to_shot:
        return animate_image_to_shot(paths, img_id)
    out = get_ai_image(paths.db_file, img_id)
    assert out is not None
    return out


def cutout_ai_image(paths: AppPaths, image_id: int) -> dict[str, Any]:
    img = get_ai_image(paths.db_file, image_id)
    if img is None:
        raise ValueError(f"AI image #{image_id} not found")
    src = paths.media_dir / str(img["image_path"])
    dst = paths.media_dir / "characters" / f"ai_img_{image_id}_cutout.png"
    key_hex = _SEED_PALETTE[abs(int(img["seed"])) % len(_SEED_PALETTE)][0].replace("#", "0x")
    _, used_rembg = remove_background_with_flag(paths, src, dst, key_color=key_hex)
    sim_flags = [f for f in (img.get("simulation_flags") or []) if f != "cutout_colorkey_fallback"]
    if not used_rembg:
        sim_flags.append("cutout_colorkey_fallback")
    rel = f"characters/{dst.name}"
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE ai_images SET cutout_path = ?, simulation_flags_json = ? WHERE id = ?",
            (rel, json.dumps(sim_flags), int(image_id)),
        )
    updated = get_ai_image(paths.db_file, image_id)
    assert updated is not None
    return updated
