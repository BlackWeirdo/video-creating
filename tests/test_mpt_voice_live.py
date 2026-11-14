"""Live voice-over render through a real MoneyPrinterTurbo service (Phase 09, FR-REN-03, FR-REN-07).

Starts the pinned MPT install in tools/mpt through MPTServiceManager (or reuses one already
listening on the configured port) and calls Edge TTS over the network. Skips if MPT is not installed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from videocreator.db import get_conn, migrate, query_one
from videocreator.engines.mpt_service import MPTServiceManager
from videocreator.paths import find_ffmpeg_binary, get_paths
from videocreator.pipeline.ffmpeg import probe_video
from videocreator.pipeline.render import render_video

SAMPLE_CLIP_1 = Path(__file__).parent / "samples" / "clip1_6s.mp4"


def _mean_volume_db(media: Path) -> float:
    proc = subprocess.run(
        [find_ffmpeg_binary("ffmpeg"), "-hide_banner", "-i", str(media), "-af", "volumedetect", "-vn", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", proc.stderr).group(1))


@pytest.mark.live
def test_voice_over_render_keeps_footage_length(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    mgr = MPTServiceManager(paths)
    if not mgr.is_healthy() and not mgr.is_installed():
        pytest.skip("MoneyPrinterTurbo is not installed in tools/mpt (run installer/install_mpt.cmd)")

    assert mgr.start() is True
    try:
        deadline = time.monotonic() + 120
        while not mgr.is_healthy() and time.monotonic() < deadline:
            time.sleep(2)
        assert mgr.is_healthy(), "MoneyPrinterTurbo did not come up within 120s"

        rel_ftg = "footage/clip1.mp4"
        abs_ftg = paths.media_dir / rel_ftg
        abs_ftg.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SAMPLE_CLIP_1, abs_ftg)
        plan = {
            "formula": "hook-first",
            "title": "Lồng tiếng thật",
            "voice_lang": "vi",
            "caption_lang": "vi",
            "shots": [
                {"shot_id": 1, "start_s": 0.0, "duration_s": 2.5, "text": "Từng đường giũa, từng chút kiên nhẫn."},
                {"shot_id": 2, "start_s": 2.5, "duration_s": 2.5, "text": "Đeo lên tay, mang theo cả tâm hồn."},
            ],
        }
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, status) "
                "VALUES (1, ?, 'sha_voice_1', 6.0, 1080, 1920, 'portrait', 'analysed')",
                (rel_ftg,),
            )
            conn.execute(
                "INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, quality) "
                "VALUES (1, 1, 1, 0.0, 3.0, 'Shot 1', '[]', 1, 5), (2, 1, 2, 2.5, 5.5, 'Shot 2', '[]', 1, 5)"
            )
            conn.execute(
                "INSERT INTO videos (id, footage_id, engine, voice_lang, status, plan_json, captions_json) "
                "VALUES (1, 1, 'mpt', 'vi', 'planned', ?, '{}')",
                (json.dumps(plan, ensure_ascii=False),),
            )

        render_video(paths, 1)
        row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = 1")
        assert row["status"] == "pending_approval"
        assert row["engine"] == "mpt"
        assert "Không lồng tiếng được" not in str(row["quality_notes"] or "")

        master = paths.media_dir / str(row["output_path"])
        info = probe_video(master)
        assert (info.width, info.height) == (1080, 1920)
        assert info.has_audio
        # Footage length (2 x 2.5 s) wins over the voice length: no truncation, no looping.
        assert abs(info.duration_s - 5.0) < 0.2
        assert _mean_volume_db(master) > -40.0, "master audio is silent: voice-over was not mixed in"
    finally:
        mgr.stop()
