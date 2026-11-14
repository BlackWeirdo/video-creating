"""Live Studio session with the real agent (`claude -p`, subscription), real voice and a real Remotion render (Phase 17).

Uses subscription quota and takes several minutes, so it only runs with RUN_STUDIO_LIVE=1.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_one
from videocreator.engines.mpt_service import MPTServiceManager
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import probe_video
from videocreator.studio.agent import run_studio_job
from videocreator.studio.session import confirm_studio_plan, create_studio_session, request_studio_revision

SAMPLES = Path(__file__).parent / "samples"


@pytest.mark.live
def test_studio_agent_live_session(tmp_path: Path) -> None:
    if os.environ.get("RUN_STUDIO_LIVE") != "1":
        pytest.skip("Set RUN_STUDIO_LIVE=1 to run full Studio live agent session")
    if shutil.which("claude") is None or shutil.which("node") is None:
        pytest.skip("claude CLI and Node.js are required")

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    cfg = load_settings(paths.config_file)
    cfg.studio.model = os.environ.get("STUDIO_LIVE_MODEL", "sonnet")
    save_settings(paths.config_file, cfg)

    with get_conn(paths.db_file) as conn:
        for fid, clip in ((1, "clip1_6s.mp4"), (2, "clip2_6s.mp4")):
            rel = f"footage/{fid}.mp4"
            (paths.media_dir / "footage").mkdir(parents=True, exist_ok=True)
            shutil.copy2(SAMPLES / clip, paths.media_dir / rel)
            conn.execute(
                "INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, status) "
                "VALUES (?, ?, ?, 6.0, 1080, 1920, 'portrait', 'analysed')",
                (fid, rel, f"sha_live_{fid}"),
            )
        conn.execute(
            "INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, quality) VALUES "
            "(1, 1, 1, 0.0, 3.0, 'Cận cảnh mặt dây bạc hình khối, xoay chậm', '[]', 1, 5), "
            "(2, 1, 2, 3.0, 6.0, 'Mặt dây bạc trên nền xám, có chữ', '[]', 1, 4), "
            "(3, 2, 1, 0.0, 3.0, 'Thợ mài nhẫn bạc bằng máy mài cầm tay', '[]', 1, 5), "
            "(4, 2, 2, 3.0, 6.0, 'Bàn tay thợ cầm nhẫn bạc soi dưới ánh đèn', '[]', 1, 4)"
        )

    # Voice-over through the real MoneyPrinterTurbo service when it is installed; stopped again at the end.
    mpt = MPTServiceManager(paths)
    voice_on = mpt.start()
    if voice_on:
        deadline = time.monotonic() + 90
        while not mpt.is_healthy() and time.monotonic() < deadline:
            time.sleep(2)
        voice_on = mpt.is_healthy()
    try:
        sid = create_studio_session(
            paths,
            prompt="Video 8-10 giây: mở đầu bằng cảnh thợ mài nhẫn, kết bằng cận cảnh mặt dây. Phụ đề ngắn, chữ hiện dần.",
            options={"voice_lang": "vi" if voice_on else "none"},
        )
        # FR-STD-05: the first run stops with the script waiting for confirmation.
        res = run_studio_job(paths, sid)
        print("studio live plan:", res)
        assert res["status"] == "awaiting_confirm"
        assert res["plan"]["shots"]

        confirm_studio_plan(paths, sid)
        res = run_studio_job(paths, sid)
        print("studio live result:", res)
        assert res["version"] == 1
        video = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (res["video_id"],))
        assert video["status"] == "pending_approval"
        info = probe_video(paths.media_dir / str(video["output_path"]))
        assert (info.width, info.height) == (1080, 1920)
        assert 5.0 <= info.duration_s <= 31.0
        out_dir = paths.media_dir / "studio" / str(sid) / "out"
        if voice_on:
            assert (out_dir / "v1.audio.wav").exists()
            assert "lồng tiếng" not in str(video["quality_notes"])

        # FR-STD-08: revise by prompt on the same agent session; the first render is kept.
        request_studio_revision(
            paths, sid, "Giữ nguyên các shot. Đổi phụ đề của cảnh cuối thành đúng câu: Làm bằng tay, từng chiếc một"
        )
        res2 = run_studio_job(paths, sid)
        print("studio live revise:", res2)
        assert res2["version"] == 2
        assert res2["session_ref"] == res["session_ref"]
        assert (out_dir / "v1.mp4").exists() and (out_dir / "v2.mp4").exists()
        assert "Làm bằng tay, từng chiếc một" in (out_dir / "v2.plan.json").read_text(encoding="utf-8")
        assert "Làm bằng tay, từng chiếc một" not in (out_dir / "v1.plan.json").read_text(encoding="utf-8")

        keep = os.environ.get("STUDIO_LIVE_KEEP_DIR")
        if keep:
            shutil.copytree(out_dir, Path(keep), dirs_exist_ok=True)
            for rel in ("output/video_%d.mp4" % res["video_id"],):
                shutil.copy2(paths.media_dir / rel, Path(keep) / "master.mp4")
    finally:
        mpt.stop()
