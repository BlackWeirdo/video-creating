"""Footage import: validation, sha256 deduplication, copy into the media folder (Phase 03)."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths
from videocreator.pipeline.probe import probe_video

ALLOWED_VIDEO_EXTENSIONS: set[str] = {".mp4", ".mov", ".mkv", ".webm"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


class DuplicateFootageError(ValueError):
    """Raised when a footage file with the same SHA-256 already exists."""


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def import_footage_file(
    paths: AppPaths,
    source_file: Path,
    *,
    product_ids: list[int],
    no_product: bool = False,
    enqueue_analysis: bool = True,
    actor: str = "ui",
) -> int:
    """Validates, probes, deduplicates by sha256, copies into media/footage/<id>.mp4,
    and optionally enqueues the `analyse` job."""
    if not source_file.exists() or not source_file.is_file():
        raise ValueError(f"Source file does not exist: {source_file}")

    ext = source_file.suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError(
            f"Unsupported video extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )

    clean_pids = sorted({int(pid) for pid in product_ids if int(pid) > 0})
    if not clean_pids and not no_product:
        raise ValueError(
            "Must select at least one product or explicitly mark 'no_product' (FR-FTG-03)"
        )
    if no_product:
        clean_pids = []

    file_size = source_file.stat().st_size
    if file_size <= 0 or file_size > MAX_UPLOAD_BYTES:
        raise ValueError(f"Invalid video file size ({file_size} bytes)")

    sha256 = compute_sha256(source_file)
    existing = query_one(
        paths.db_file, "SELECT id FROM footage WHERE sha256 = ?", (sha256,)
    )
    if existing is not None:
        raise DuplicateFootageError(
            f"Duplicate footage rejected (matches footage #{existing['id']}, sha256={sha256[:12]}...)"
        )

    info = probe_video(source_file)
    crop_data: dict[str, Any] | None = None
    if info.is_landscape:
        crop_data = {"mode": "blur_pad", "x_offset_ratio": 0.5}

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO footage (
                path, sha256, duration_s, width, height, orientation,
                crop_json, product_ids_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'imported')
            """,
            (
                "pending",
                sha256,
                info.duration_s,
                info.width,
                info.height,
                info.orientation,
                json.dumps(crop_data) if crop_data else None,
                json.dumps(clean_pids),
            ),
        )
        footage_id = int(cur.lastrowid or 0)
        rel_path = f"footage/{footage_id}.mp4"
        dest_file = paths.media_dir / rel_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, dest_file)

        conn.execute(
            "UPDATE footage SET path = ? WHERE id = ?",
            (rel_path, footage_id),
        )
        record_audit(
            conn,
            actor=actor,
            action="footage.imported",
            object_type="footage",
            object_id=footage_id,
            detail=f"sha256={sha256[:12]}, {info.width}x{info.height}, {info.duration_s}s",
        )

    if enqueue_analysis:
        enqueue_job(paths.db_file, "analyse", ref_id=footage_id)

    return footage_id
