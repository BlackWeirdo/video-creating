"""Tests for Phase 12: FreeCut (MIT) Bridge & Multi-Track Timeline Editor Composer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import get_conn, query_one
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_video

pytestmark = pytest.mark.local


def _make_sample_clip(dest: Path, *, duration_s: float = 2.6, freq: int = 440) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s=360x640:r=30:d={duration_s}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:sample_rate=48000:duration={duration_s}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            "2",
            str(dest),
        ]
    )
    return dest


def test_freecut_bridge_and_multitrack_timeline_composer(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        # 1. FreeCut endpoint & V1 /assets route coexistence
        fc = client.get("/freecut")
        assert fc.status_code == 200
        assert len(fc.text) > 100
        assert client.get("/assets").status_code == 200

        # Prepare a rendered video in SQLite + disk
        clip_a = _make_sample_clip(paths.output_dir / "v100.mp4", duration_s=2.6, freq=440)
        clip_b = _make_sample_clip(paths.footage_dir / "broll_clip.mp4", duration_s=2.6, freq=620)
        edited_bytes = _make_sample_clip(tmp_path / "freecut_exported.mp4", duration_s=3.2, freq=520).read_bytes()

        with get_conn(paths.db_file) as conn:
            v_id = int(
                conn.execute(
                    """
                    INSERT INTO videos (
                        workspace_id, engine, status, plan_json, output_path, duration_s
                    )
                    VALUES (1, 'ffmpeg', 'pending_approval', ?, 'output/v100.mp4', 2.6)
                    """,
                    (
                        json.dumps(
                            {
                                "title": "Nhan bac cut bridge",
                                "shots": [{"shot_id": 1, "duration_s": 2.6, "text": "Mo dau bridge"}],
                            }
                        ),
                    ),
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO footage (workspace_id, path, sha256, orientation, width, height, duration_s) VALUES (1, 'footage/broll_clip.mp4', 'sha_fc_broll_1', 'portrait', 360, 640, 2.6)"
            )

        # 2. FreeCut Bridge contract: GET job, heartbeat, PUT exported result
        missing_job = client.get("/api/editor/jobs/999999")
        assert missing_job.status_code == 200
        assert missing_job.json()["state"] == "missing"

        job_state = client.get(f"/api/editor/jobs/{v_id}")
        assert job_state.status_code == 200
        payload = job_state.json()
        assert payload["state"] == "ready"
        assert payload["project"]["video_url"] == "/files/output/v100.mp4"
        assert len(payload["project"]["subs"]) == 1

        hb = client.post("/api/editor/heartbeat", json={"job": str(v_id)})
        assert hb.status_code == 200 and hb.json()["ok"] is True

        put_res = client.put(
            f"/api/editor/result?name=edited_master.mp4&job={v_id}",
            content=edited_bytes,
        )
        assert put_res.status_code == 200
        saved = put_res.json()
        assert saved["video_id"] == v_id
        assert saved["qc"]["passed"] is True
        v_after = query_one(paths.db_file, "SELECT output_path, duration_s FROM videos WHERE id = ?", (v_id,))
        assert v_after is not None
        assert "freecut" in str(v_after["output_path"])
        assert float(v_after["duration_s"]) >= 3.0

        # 3. Workspace Media & Multi-track Timeline Composer render
        media = client.get("/api/v1/editor/media?workspace_id=1")
        assert media.status_code == 200
        assert len(media.json()["videos"]) >= 1

        cr = client.post(
            "/api/v1/editor/projects",
            json={
                "workspace_id": 1,
                "title": "Timeline Multi Clip",
                "tracks": {
                    "video_clips": [
                        {"source_path": "footage/broll_clip.mp4", "start_s": 0.0, "duration_s": 2.4},
                        {"source_path": "output/v100.mp4", "start_s": 0.0, "duration_s": 2.4},
                    ],
                    "audio_clips": [],
                    "subtitles": [
                        {"start_s": 0.1, "end_s": 2.3, "text": "Canh 1 Timeline"},
                        {"start_s": 2.5, "end_s": 4.7, "text": "Canh 2 Timeline"},
                    ],
                },
            },
        )
        assert cr.status_code == 201
        ep_id = int(cr.json()["project"]["id"])

        rn = client.post(
            f"/api/v1/editor/projects/{ep_id}/render",
            json={"style_preset": "box_highlight"},
        )
        assert rn.status_code == 200, rn.text
        done = rn.json()["project"]
        assert done["status"] == "completed"
        out_vid = int(done["output_video_id"])
        out_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (out_vid,))
        assert out_row is not None
        assert json.loads(out_row["qc_json"])["passed"] is True
        assert probe_video(paths.media_dir / str(out_row["output_path"])).duration_s >= 4.4
