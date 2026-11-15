"""Generative B-roll orchestration, budget enforcement, preview, and shot-library import (Phase 14)."""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_video

logger = logging.getLogger("videocreator.pipeline.broll")


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
