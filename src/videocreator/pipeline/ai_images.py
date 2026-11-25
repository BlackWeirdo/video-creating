"""AI Image Studio: Gemini Imagen 3 generation with local studio fallback, RGBA cutout & motion shots."""
from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path
from typing import Any

from videocreator.ai.budget import get_daily_api_spend, record_usage
from videocreator.ai.key_pool import (
    acquire_api_key,
    mark_pooled_key_cooldown,
    mark_pooled_key_ok,
)
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import hydrate_row
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import SEED_PALETTE, render_styled_still_png
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.ai_images")

IMAGEN_MODEL = "imagen-3.0-generate-002"
IMAGEN_COST_USD = 0.03


def image_dims(aspect_ratio: str) -> tuple[int, int]:
    ratio = (aspect_ratio or "9:16").strip()
    if ratio == "16:9":
        return 960, 540
    if ratio == "1:1":
        return 720, 720
    return 540, 960


def _hydrate_image(row: dict[str, Any]) -> dict[str, Any]:
    return hydrate_row(
        row,
        json_fields={"simulation_flags": ("simulation_flags_json", [])},
        bool_fields=("is_product_shot",),
    )


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


def _composite_overlay_png(bg_png: Path, overlay_png: Path, dest_png: Path, *, w: int, h: int) -> None:
    ov_w = max(80, int(w * 0.58))
    ov_h = max(80, int(h * 0.52))
    fc = (
        f"[0:v]scale={w}:{h}[bg];"
        f"[1:v]scale={ov_w}:{ov_h}:force_original_aspect_ratio=decrease[char];"
        f"[bg][char]overlay=(W-w)/2:(H-h)/2,format=rgb24[vout]"
    )
    run_ffmpeg(
        [
            "-i",
            str(bg_png.resolve()),
            "-i",
            str(overlay_png.resolve()),
            "-filter_complex",
            fc,
            "-map",
            "[vout]",
            "-frames:v",
            "1",
            "-c:v",
            "png",
            str(dest_png.resolve()),
        ],
        allow_creative_filters=True,
    )


def _try_generate_gemini_imagen_png(
    paths: AppPaths,
    *,
    prompt: str,
    aspect_ratio: str,
    w: int,
    h: int,
    dest_png: Path,
    overlay_image: Path | None = None,
) -> bool:
    """Attempts real AI image generation via Google GenAI Imagen 3 within daily generative budget."""
    settings = load_settings(paths.config_file)
    if str(settings.ai.policy.api_fallback).strip().lower() == "never":
        return False

    spent = get_daily_api_spend(paths.db_file, bucket="generative")
    limit_usd = float(settings.budget.generative_daily_usd)
    if spent >= limit_usd or (spent + IMAGEN_COST_USD) > limit_usd:
        return False

    api_key, key_id = acquire_api_key(paths, "gemini", legacy_secret_name="GEMINI_API_KEY")
    if not api_key:
        return False

    try:
        from google import genai  # type: ignore[import-untyped]
        from google.genai import types  # type: ignore[import-untyped]

        imagen_ratio = aspect_ratio if aspect_ratio in ("9:16", "16:9", "1:1", "3:4", "4:3") else "9:16"
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_images(
            model=IMAGEN_MODEL,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio=imagen_ratio,
                output_mime_type="image/png",
            ),
        )
        gen_images = getattr(resp, "generated_images", None) or []
        if not gen_images:
            raise RuntimeError("Imagen returned zero generated_images")
        img_obj = getattr(gen_images[0], "image", None)
        img_bytes = getattr(img_obj, "image_bytes", None)
        if not img_bytes:
            raise RuntimeError("Imagen returned empty image_bytes")

        dest_png.parent.mkdir(parents=True, exist_ok=True)
        if overlay_image is not None and overlay_image.exists():
            tmp_bg = dest_png.with_name(f"{dest_png.stem}_imagen_bg.png")
            tmp_bg.write_bytes(bytes(img_bytes))
            try:
                _composite_overlay_png(tmp_bg, overlay_image, dest_png, w=w, h=h)
            finally:
                tmp_bg.unlink(missing_ok=True)
        else:
            dest_png.write_bytes(bytes(img_bytes))

        mark_pooled_key_ok(paths.db_file, key_id)
        record_usage(
            paths.db_file,
            provider="gemini_imagen",
            model=IMAGEN_MODEL,
            kind="videogen",
            route="api",
            units_in=1,
            units_out=1,
            cost_usd=IMAGEN_COST_USD,
        )
        return True
    except Exception as exc:
        lower_err = str(exc).lower()
        if any(m in lower_err for m in ("429", "quota", "resource_exhausted", "401", "403", "api_key_invalid")):
            mark_pooled_key_cooldown(paths.db_file, key_id, str(exc))
        logger.warning("Gemini Imagen 3 unavailable; falling back to local studio canvas: %s", exc)
        return False


def _try_generate_muse_image_png(
    paths: AppPaths,
    *,
    prompt: str,
    aspect_ratio: str,
    w: int,
    h: int,
    dest_png: Path,
    overlay_image: Path | None = None,
) -> bool:
    """Attempts image generation via hardened Muse Gateway (`/v1/images/generations`, `$0` subscription)."""
    import base64

    from videocreator.muse_gateway.client import MuseGatewayClient
    from videocreator.muse_gateway.errors import MuseGatewayError
    from videocreator.secrets_store import SecretsStore

    settings = load_settings(paths.config_file)
    cfg = settings.muse_gateway
    if not cfg.enabled:
        return False

    size = (
        "1792x1024"
        if aspect_ratio == "16:9"
        else ("1024x1024" if aspect_ratio == "1:1" else "1024x1792")
    )
    try:
        secrets = SecretsStore(paths.secrets_file)
        client = MuseGatewayClient(cfg, secrets, timeout_s=180.0)
        client.verify_ready_and_safe()
        model_name = cfg.default_image_model or "muse-image"
        resp = client.generate_images(
            prompt=prompt,
            model=model_name,
            n=1,
            size=size,
            response_format="b64_json",
        )
        items = resp.get("data") if isinstance(resp, dict) else []
        if not items or not isinstance(items[0], dict):
            raise MuseGatewayError("Muse Gateway returned empty image data list")
        first = items[0]
        raw_bytes: bytes | None = None
        if first.get("b64_json"):
            raw_bytes = base64.b64decode(str(first["b64_json"]))
        elif first.get("url"):
            tmp_dl = dest_png.with_name(f"{dest_png.stem}_muse_dl.png")
            client.download_media_to_file(str(first["url"]), tmp_dl)
            raw_bytes = tmp_dl.read_bytes()
            tmp_dl.unlink(missing_ok=True)
        if not raw_bytes:
            raise MuseGatewayError("Muse Gateway image entry contained neither b64_json nor url")

        dest_png.parent.mkdir(parents=True, exist_ok=True)
        if overlay_image is not None and overlay_image.exists():
            tmp_bg = dest_png.with_name(f"{dest_png.stem}_muse_bg.png")
            tmp_bg.write_bytes(raw_bytes)
            try:
                _composite_overlay_png(tmp_bg, overlay_image, dest_png, w=w, h=h)
            finally:
                tmp_bg.unlink(missing_ok=True)
        else:
            dest_png.write_bytes(raw_bytes)

        record_usage(
            paths.db_file,
            provider="muse_gateway",
            model=model_name,
            kind="videogen",
            route="subscription",
            units_in=1,
            units_out=1,
            cost_usd=0.0,
        )
        return True
    except Exception as exc:
        logger.warning("Muse Gateway image generation unavailable; falling back: %s", exc)
        return False


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

    w, h = image_dims(str(row.get("aspect_ratio") or "9:16"))
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
    """Generates a consistent-character scene PNG via Gemini Imagen 3 or tagged local canvas fallback."""
    from videocreator.pipeline.characters import get_character

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
    w, h = image_dims(ratio)

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
    used_imagen = _try_generate_gemini_imagen_png(
        paths,
        prompt=merged_prompt,
        aspect_ratio=ratio,
        w=w,
        h=h,
        dest_png=dest_png,
        overlay_image=overlay_path,
    )
    if used_imagen:
        provider_used = "gemini_imagen"
        sim_flags: list[str] = []
    elif _try_generate_muse_image_png(
        paths,
        prompt=merged_prompt,
        aspect_ratio=ratio,
        w=w,
        h=h,
        dest_png=dest_png,
        overlay_image=overlay_path,
    ):
        provider_used = "muse_image"
        sim_flags = []
    else:
        render_styled_still_png(dest_png, w=w, h=h, seed=locked_seed, overlay_image=overlay_path)
        provider_used = "local_card"
        sim_flags = ["ai_image_canvas_placeholder"]

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE ai_images SET image_path = ?, provider = ?, simulation_flags_json = ? WHERE id = ?",
            (rel_png, provider_used, json.dumps(sim_flags), img_id),
        )
        record_audit(
            conn,
            actor=actor,
            action="generate_ai_image",
            object_type="ai_image",
            object_id=img_id,
            detail=f"provider={provider_used} char={character_id} seed={locked_seed} ratio={ratio}",
        )

    if animate_to_shot:
        return animate_image_to_shot(paths, img_id)
    out = get_ai_image(paths.db_file, img_id)
    assert out is not None
    return out


def cutout_ai_image(paths: AppPaths, image_id: int) -> dict[str, Any]:
    from videocreator.pipeline.characters import remove_background_with_flag

    img = get_ai_image(paths.db_file, image_id)
    if img is None:
        raise ValueError(f"AI image #{image_id} not found")
    src = paths.media_dir / str(img["image_path"])
    dst = paths.media_dir / "characters" / f"ai_img_{image_id}_cutout.png"
    key_hex = SEED_PALETTE[abs(int(img["seed"])) % len(SEED_PALETTE)][0].replace("#", "0x")
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


__all__ = [
    "IMAGEN_COST_USD",
    "IMAGEN_MODEL",
    "animate_image_to_shot",
    "cutout_ai_image",
    "generate_ai_image",
    "get_ai_image",
    "image_dims",
    "list_ai_images",
]
