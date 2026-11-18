"""Batch render: one `render` job per planned video (`FR-REN-09`)."""
from __future__ import annotations

from pathlib import Path

from videocreator.db import query_all


def enqueue_batch_render(db_file: Path) -> list[int]:
    """Enqueues sequential `render` jobs for all videos currently in `planned` status (`FR-REN-09`)."""
    from videocreator.jobs import enqueue_job

    rows = query_all(
        db_file,
        "SELECT id FROM videos WHERE status = 'planned' AND COALESCE(engine, 'ffmpeg') != 'studio' ORDER BY id ASC",
    )
    job_ids: list[int] = []
    for r in rows:
        vid = int(r["id"])
        jid = enqueue_job(db_file, "render", ref_id=vid)
        job_ids.append(jid)
    return job_ids

