"""Fulfilling a manual ticket: the delivered video is checked and filed as a B-roll shot."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from videocreator.ai.budget import record_usage
from videocreator.db import get_conn, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.probe import probe_video

logger = logging.getLogger("videocreator.manual.tickets")

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
MAX_MANUAL_VIDEO_MB = 200.0


def fulfill_manual_ticket(
    paths: AppPaths,
    ticket_id: int,
    file_path: Path,
    *,
    actor: str = "manual",
) -> tuple[int, int]:
    """Validates `file_path` via ffprobe and imports it as an `assets(kind='broll')` + `shots(ai_broll, has_product=0)`.

    Returns `(asset_id, shot_id)`.
    """
    ticket = query_one(
        paths.db_file,
        "SELECT * FROM manual_tickets WHERE id = ?",
        (ticket_id,),
    )
    if ticket is None:
        raise LookupError(f"Manual ticket #{ticket_id} not found")
    if str(ticket["status"]) not in ("open", "reminded"):
        raise ValueError(f"Manual ticket #{ticket_id} is already '{ticket['status']}'")

    if not file_path.exists() or not file_path.is_file():
        raise ValueError(f"File does not exist: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTS:
        raise ValueError(f"Unsupported video file extension '{ext}' (expected MP4/MOV/WEBM)")

    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb <= 0 or size_mb > MAX_MANUAL_VIDEO_MB:
        raise ValueError(f"Invalid video size {size_mb:.2f} MB")

    try:
        info = probe_video(file_path)
    except Exception as exc:
        raise ValueError(f"Invalid video file (ffprobe failed): {exc}") from exc

    if info.duration_s <= 0.3 or info.width <= 0 or info.height <= 0:
        raise ValueError("Video file has invalid duration or dimensions")

    rel_dest = f"assets/broll_ticket_{ticket_id}.mp4"
    abs_dest = paths.media_dir / rel_dest
    abs_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, abs_dest)

    meta = {
        "source": "manual_ticket",
        "ticket_id": ticket_id,
        "prompt": ticket["prompt"],
        "width": info.width,
        "height": info.height,
    }
    tags = ["ai_broll", "manual_broll"]

    with get_conn(paths.db_file) as conn:
        a_cur = conn.execute(
            """
            INSERT INTO assets (kind, path, duration_s, meta_json)
            VALUES ('broll', ?, ?, ?)
            """,
            (rel_dest, round(info.duration_s, 3), json.dumps(meta, ensure_ascii=False)),
        )
        asset_id = int(a_cur.lastrowid or 0)

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
                round(info.duration_s, 3),
                str(ticket["prompt"]),
                json.dumps(tags, ensure_ascii=False),
            ),
        )
        shot_id = int(s_cur.lastrowid or 0)

        conn.execute(
            """
            UPDATE manual_tickets
            SET status = 'closed',
                result_asset_id = ?,
                closed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (asset_id, ticket_id),
        )
        record_audit(
            conn,
            actor=actor,
            action="manual_ticket.fulfilled",
            object_type="manual_ticket",
            object_id=ticket_id,
            detail=f"asset_id={asset_id}, shot_id={shot_id}",
        )

    record_usage(
        paths.db_file,
        provider="manual_station",
        model="subscription_app",
        kind="videogen",
        route="manual",
        cost_usd=0.0,
    )
    return asset_id, shot_id
