"""Local tests for MPT-to-FFmpeg fallback and batch render queue (Phase 09, FR-REN-05, FR-REN-09)."""
from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_all, query_one
from videocreator.paths import get_paths
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.render import render_video
from videocreator.pipeline.render_batch import enqueue_batch_render

SAMPLE_CLIP_1 = Path(__file__).parent / "samples" / "clip1_6s.mp4"


@pytest.mark.local
def test_mpt_engine_offline_automatically_falls_back_to_ffmpeg(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    # Point the app at a port nothing listens on, so a real MPT running on the default port is not used.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    cfg = load_settings(paths.config_file)
    cfg.mpt.port = closed_port
    save_settings(paths.config_file, cfg)

    rel_ftg = "footage/clip1.mp4"
    abs_ftg = paths.media_dir / rel_ftg
    abs_ftg.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAMPLE_CLIP_1, abs_ftg)

    plan_payload = {
        "formula": "hook-first",
        "title": "Thử nghiệm lùi về FFmpeg",
        "voice_lang": "vi",
        "caption_lang": "vi",
        "shots": [
            {"shot_id": 1, "start_s": 0.0, "duration_s": 2.5, "text": "Nhẫn bạc S925"},
            {"shot_id": 2, "start_s": 2.5, "duration_s": 2.5, "text": "Chế tác thủ công"},
        ],
    }

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, status)
            VALUES (1, ?, 'sha_mpt_1', 6.0, 1080, 1920, 'portrait', 'analysed')
            """,
            (rel_ftg,),
        )
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, quality)
            VALUES
              (1, 1, 1, 0.0, 3.0, 'Shot 1', '["product"]', 1, 5),
              (2, 1, 2, 2.5, 5.5, 'Shot 2', '["process"]', 1, 5)
            """
        )
        conn.execute(
            """
            INSERT INTO videos (id, footage_id, engine, voice_lang, status, plan_json, captions_json)
            VALUES (1, 1, 'mpt', 'vi', 'planned', ?, '{}')
            """,
            (json.dumps(plan_payload, ensure_ascii=False),),
        )
        conn.execute(
            """
            INSERT INTO videos (id, footage_id, engine, voice_lang, status, plan_json, captions_json)
            VALUES (2, 1, 'ffmpeg', 'none', 'planned', ?, '{}')
            """,
            (json.dumps(plan_payload, ensure_ascii=False),),
        )

    # Batch queue test (FR-REN-09)
    queued_job_ids = enqueue_batch_render(paths.db_file)
    assert len(queued_job_ids) == 2
    jobs = query_all(paths.db_file, "SELECT * FROM jobs WHERE kind = 'render'")
    assert len(jobs) == 2

    # Render Video #1 which requested engine='mpt' while MPT service is offline -> falls back to ffmpeg
    render_video(paths, 1)
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = 1")
    assert v_row is not None
    assert v_row["status"] == "pending_approval"
    assert v_row["engine"] == "ffmpeg"
    assert "Không lồng tiếng được" in str(v_row["quality_notes"] or "")

    out_mp4 = paths.media_dir / str(v_row["output_path"])
    assert out_mp4.exists()
    info = probe_video(out_mp4)
    assert info.width == 1080
    assert info.height == 1920
