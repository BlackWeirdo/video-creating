"""`analyse` job: shot detection and thumbnails for one footage (Phase 03)."""
from __future__ import annotations

import json
import shutil

from videocreator.db import get_conn, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.shots import detect_shots
from videocreator.pipeline.thumbs import extract_thumbnail
from videocreator.state import transition_footage


def run_analyse_footage(paths: AppPaths, footage_id: int) -> str:
    """Job handler for `analyse`: detects shots via rea-video, extracts thumbnails,
    and saves shots in a single transaction."""
    row = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (footage_id,))
    if row is None:
        raise LookupError(f"Footage #{footage_id} does not exist")

    video_path = paths.media_dir / str(row["path"])
    duration_s = float(row["duration_s"] or 0.0)
    product_ids_json = str(row.get("product_ids_json") or "[]")
    try:
        product_ids = json.loads(product_ids_json)
    except json.JSONDecodeError:
        product_ids = []
    has_product = 1 if product_ids else 0

    transition_footage(paths.db_file, footage_id, "analysing", error=None)
    work_dir = paths.work_dir / f"analyse_{footage_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)

    try:
        if duration_s <= 0:
            info = probe_video(video_path)
            duration_s = info.duration_s

        spans, rea_log = detect_shots(
            video_path,
            total_duration_s=duration_s,
            work_dir=work_dir,
        )
        shot_records: list[tuple[int, float, float, str]] = []
        for idx, span in enumerate(spans, start=1):
            rel_thumb = f"thumbs/shot_{footage_id}_{idx:03d}.jpg"
            abs_thumb = paths.media_dir / rel_thumb
            extract_thumbnail(video_path, span.midpoint_s, abs_thumb)
            shot_records.append((idx, span.start_s, span.end_s, rel_thumb))

        with get_conn(paths.db_file) as conn:
            conn.execute("DELETE FROM shots WHERE footage_id = ?", (footage_id,))
            for idx, start_s, end_s, rel_thumb in shot_records:
                conn.execute(
                    """
                    INSERT INTO shots (
                        footage_id, idx, start_s, end_s, description,
                        tags_json, has_product, product_ids_json, quality, thumb_path
                    )
                    VALUES (?, ?, ?, ?, '', '[]', ?, ?, 3, ?)
                    """,
                    (
                        footage_id,
                        idx,
                        start_s,
                        end_s,
                        has_product,
                        product_ids_json,
                        rel_thumb,
                    ),
                )
            conn.execute(
                "UPDATE footage SET status = 'analysed', error = NULL WHERE id = ?",
                (footage_id,),
            )
            record_audit(
                conn,
                actor="worker",
                action="footage.analysed",
                object_type="footage",
                object_id=footage_id,
                detail=f"{len(shot_records)} shots",
            )
        shutil.rmtree(work_dir, ignore_errors=True)
        return f"Detected {len(shot_records)} shots\n{rea_log}"
    except Exception as exc:
        err_msg = str(exc)[:500]
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE footage SET status = 'failed', error = ? WHERE id = ?",
                (err_msg, footage_id),
            )
        raise
