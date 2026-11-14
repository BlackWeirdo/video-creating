"""Generative B-roll orchestration, budget enforcement, preview, and shot-library import (Phase 14)."""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from videocreator.ai.budget import check_budget, record_usage
from videocreator.ai.gateway import GatewayVideoGenProvider
from videocreator.ai.veo import VeoVideoGenProvider
from videocreator.ai.videogen_base import VideoGenProvider, estimate_videogen_cost
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, record_audit
from videocreator.manual.tickets import create_manual_ticket
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import probe_video, run_ffmpeg
from videocreator.secrets_store import SecretsStore

logger = logging.getLogger("videocreator.pipeline.broll")

BROLL_PRESET_PROMPTS: list[dict[str, str]] = [
    {
        "id": "workbench",
        "label": "Bàn thợ bạc thủ công (ánh đèn vàng ấm)",
        "prompt": "Cận cảnh bàn gỗ của nghệ nhân kim hoàn, dụng cụ chạm khắc cổ điển, bụi bạc lấp lánh dưới ánh đèn vàng ấm, chuyển động máy chậm, 9:16 dọc, không có trang sức hoàn thiện",
    },
    {
        "id": "smoke_light",
        "label": "Khói mỏng & tia sáng nghệ thuật",
        "prompt": "Làn khói mỏng bay chậm qua tia sáng chiếu xiên trên nền đá tối màu sang trọng, bokeh dịu, điện ảnh, 9:16 dọc",
    },
    {
        "id": "nature_stone",
        "label": "Đá tự nhiên & rêu ẩm (bối cảnh trưng bày)",
        "prompt": "Bề mặt đá bazan đen tự nhiên và rêu xanh ẩm dưới nắng sớm dịu nhẹ, giọt sương tinh khiết, chuyển động dolly chậm, 9:16 dọc",
    },
]


def get_videogen_provider(
    paths: AppPaths,
    source_key: str,
) -> VideoGenProvider:
    settings = load_settings(paths.config_file)
    secrets = SecretsStore(paths.secrets_file)
    clean = source_key.replace("gateway_api:", "").replace("_api", "").strip().lower()
    if clean == "veo":
        return VeoVideoGenProvider(settings, secrets, paths.work_dir)
    return GatewayVideoGenProvider(clean, settings, secrets, paths.work_dir)


def normalize_broll_clip(src_mp4: Path, dest_mp4: Path) -> float:
    """Normalizes a generated B-roll clip to 1080x1920 30fps H.264 MP4 and returns duration_s."""
    dest_mp4.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(src_mp4.resolve()),
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(dest_mp4.resolve()),
        ]
    )
    info = probe_video(dest_mp4)
    return float(info.duration_s)


def keep_broll_clip(
    paths: AppPaths,
    clip_path: Path,
    *,
    prompt: str,
    source_model: str,
    tag_kind: str = "ai_broll",
    actor: str = "ui",
) -> tuple[int, int]:
    """Saves a previewed B-roll clip into `assets(kind='broll')` and `shots(has_product=0, tags=[tag_kind])` (`FR-BRL-01`).

    Returns `(asset_id, shot_id)`.
    """
    if not clip_path.exists():
        raise FileNotFoundError(f"B-roll clip not found: {clip_path}")

    stamp = int(time.time() * 1000)
    rel_dest = f"assets/broll_{source_model}_{stamp}.mp4"
    abs_dest = paths.media_dir / rel_dest
    abs_dest.parent.mkdir(parents=True, exist_ok=True)

    info = probe_video(clip_path)
    if info.width == 1080 and info.height == 1920:
        shutil.copy2(clip_path, abs_dest)
        duration_s = float(info.duration_s)
    else:
        duration_s = normalize_broll_clip(clip_path, abs_dest)

    tags = [tag_kind]
    if tag_kind != "ai_broll":
        tags.append(tag_kind)
    meta = {
        "source": source_model,
        "prompt": prompt,
        "tag": tag_kind,
    }

    with get_conn(paths.db_file) as conn:
        a_cur = conn.execute(
            """
            INSERT INTO assets (kind, path, duration_s, meta_json)
            VALUES ('broll', ?, ?, ?)
            """,
            (rel_dest, round(duration_s, 3), json.dumps(meta, ensure_ascii=False)),
        )
        asset_id = int(a_cur.lastrowid or 0)

        # Enforce BR-PRD-07: B-roll shots NEVER have has_product=1
        s_cur = conn.execute(
            """
            INSERT INTO shots (
                footage_id, asset_id, idx, start_s, end_s,
                description, tags_json, has_product, product_ids_json, quality
            )
            VALUES (NULL, ?, 1, 0.0, ?, ?, ?, 0, '[]', 4)
            """,
            (
                asset_id,
                round(duration_s, 3),
                prompt.strip(),
                json.dumps(tags, ensure_ascii=False),
            ),
        )
        shot_id = int(s_cur.lastrowid or 0)

        record_audit(
            conn,
            actor=actor,
            action="broll.kept",
            object_type="shot",
            object_id=shot_id,
            detail=f"asset_id={asset_id}, source={source_model}",
        )

    return asset_id, shot_id


def generate_broll(
    paths: AppPaths,
    *,
    prompt: str,
    source: str = "manual",
    seconds: int = 6,
    image_path: Path | None = None,
    provider: VideoGenProvider | None = None,
    auto_keep: bool = True,
) -> dict[str, Any]:
    """Generates a B-roll clip via the selected `source` (`manual`, `kling`, `seedance`, `veo`, etc.).

    Checks `budget.generative_daily_usd` BEFORE calling any paid API (`BR-COST-02`, `FR-BRL-03`).
    """
    clean_source = source.replace("gateway_api:", "").replace("_api", "").strip().lower()
    if clean_source == "manual":
        tid = create_manual_ticket(
            paths,
            prompt=prompt,
            seconds=seconds,
            ref_path=str(image_path) if image_path else None,
        )
        return {
            "mode": "manual",
            "ticket_id": tid,
            "estimated_cost_usd": 0.0,
        }

    settings = load_settings(paths.config_file)
    est_cost = estimate_videogen_cost(settings, clean_source, seconds)

    # Enforce generative daily budget ceiling BEFORE calling API
    check_budget(
        paths.db_file,
        settings,
        kind="videogen",
        estimated_cost_usd=est_cost,
    )

    gen = provider or get_videogen_provider(paths, clean_source)
    raw_clip = gen.generate_clip(prompt, seconds=seconds, image=image_path)

    record_usage(
        paths.db_file,
        provider=gen.name,
        model=clean_source,
        kind="videogen",
        route="api",
        units_in=1,
        units_out=seconds,
        cost_usd=est_cost,
    )

    if auto_keep:
        asset_id, shot_id = keep_broll_clip(
            paths,
            raw_clip,
            prompt=prompt,
            source_model=clean_source,
            tag_kind="ai_broll",
        )
        return {
            "mode": "api",
            "source": clean_source,
            "asset_id": asset_id,
            "shot_id": shot_id,
            "estimated_cost_usd": est_cost,
        }

    return {
        "mode": "api_preview",
        "source": clean_source,
        "preview_path": str(raw_clip),
        "estimated_cost_usd": est_cost,
    }


def list_broll_shots(db_file: Path) -> list[dict[str, Any]]:
    return query_all(
        db_file,
        """
        SELECT s.*, a.path AS asset_path, a.meta_json
        FROM shots s
        JOIN assets a ON s.asset_id = a.id
        WHERE a.kind = 'broll'
        ORDER BY s.id DESC
        """,
    )
