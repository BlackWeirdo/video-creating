"""Tests for Phase 14: Novel Multi-Chapter, Podcast 16:9 Spectrum, and Lip-sync AI Studios."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import query_one
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_video

pytestmark = pytest.mark.local


def test_novel_multichapter_render_checkpoint_resume_and_policy(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        ws_strict = int(
            client.post(
                "/api/v1/workspaces",
                json={"name": "Strict Brand", "content_policy": "strict_footage"},
            ).json()["workspace"]["id"]
        )
        ws_ai = int(
            client.post(
                "/api/v1/workspaces",
                json={"name": "Novel AI Channel", "content_policy": "full_ai"},
            ).json()["workspace"]["id"]
        )
        ch_res = client.post(
            "/api/v1/characters",
            json={
                "workspace_id": ws_ai,
                "name": "Minh Anh Narrator",
                "appearance_prompt": "Ao dai xanh co dien, anh sang am",
                "seed": 4242,
            },
        )
        char_id = int(ch_res.json()["character"]["id"])

        novel_text = (
            "Chương 1: Bức thư lúc nửa đêm\n"
            "Giữa cơn mưa rào tháng bảy, An tìm thấy chiếc hộp gỗ cũ trên gác mái cùng bức thư viết tay.\n\n"
            "Chương 2: Chìa khóa tiệm bạc\n"
            "Sáng hôm sau, dòng chữ mờ dẫn cậu tới con hẻm nhỏ nơi lò rèn bạc trăm tuổi vẫn đỏ lửa."
        )

        prev = client.post(
            "/api/v1/novels/split-preview",
            json={"source_text": novel_text, "target_words_per_chapter": 120},
        )
        assert prev.status_code == 200
        assert prev.json()["total_chapters"] == 2

        # strict_footage workspace must reject AI novel rendering
        strict_nov = client.post(
            "/api/v1/novels/projects",
            json={"workspace_id": ws_strict, "title": "Forbidden", "source_text": novel_text},
        ).json()["project"]
        r_forbid = client.post(
            f"/api/v1/novels/projects/{strict_nov['id']}/render",
            json={"sync": True},
        )
        assert r_forbid.status_code == 403

        cr = client.post(
            "/api/v1/novels/projects",
            json={
                "workspace_id": ws_ai,
                "title": "Bí ẩn Tiệm Bạc Cũ",
                "source_text": novel_text,
                "character_id": char_id,
                "style_preset": "minimal_bottom",
            },
        )
        assert cr.status_code == 201
        pid = int(cr.json()["project"]["id"])
        assert cr.json()["project"]["total_chapters"] == 2

        rn1 = client.post(f"/api/v1/novels/projects/{pid}/render", json={"sync": True})
        assert rn1.status_code == 200, rn1.text
        done1 = rn1.json()["project"]
        assert done1["status"] == "completed"
        assert done1["ready_chapters"] == 2
        assert done1["resume_stats"]["rendered_now"] == 2
        assert done1["resume_stats"]["skipped_checkpoint"] == 0

        first_vid_ids = [int(c["video_id"]) for c in done1["chapters"]]
        for ch in done1["chapters"]:
            mp4 = paths.media_dir / str(ch["output_path"])
            assert mp4.is_file()
            assert probe_video(mp4).duration_s >= 5.0

        # Checkpoint resume: second run skips already-ready chapters
        rn2 = client.post(f"/api/v1/novels/projects/{pid}/render", json={"sync": True})
        assert rn2.status_code == 200
        done2 = rn2.json()["project"]
        assert done2["resume_stats"]["rendered_now"] == 0
        assert done2["resume_stats"]["skipped_checkpoint"] == 2
        assert [int(c["video_id"]) for c in done2["chapters"]] == first_vid_ids


def test_podcast_16_9_spectrum_and_wave_visualizer(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        ws_id = int(
            client.post(
                "/api/v1/workspaces",
                json={
                    "name": "Podcast Studio",
                    "content_policy": "full_ai",
                    "default_aspect_ratio": "16:9",
                },
            ).json()["workspace"]["id"]
        )

        cr = client.post(
            "/api/v1/podcasts/projects",
            json={
                "workspace_id": ws_id,
                "title": "Tech Talk Tập 1",
                "aspect_ratio": "16:9",
                "waveform_style": "spectrum",
                "accent_color": "#38bdf8",
                "dialogue": [
                    {
                        "speaker": "Lan Anh",
                        "voice": "vi-VN-HoaiMyNeural",
                        "text": "Chào mừng các bạn quay lại bản tin công nghệ sáng tác video thông minh.",
                    },
                    {
                        "speaker": "Minh Quân",
                        "voice": "vi-VN-NamMinhNeural",
                        "text": "Hôm nay chúng ta phân tích quy trình tự động hóa sản xuất đa kênh chuẩn mười sáu chín.",
                    },
                ],
            },
        )
        assert cr.status_code == 201
        pid = int(cr.json()["project"]["id"])

        rn = client.post(
            f"/api/v1/podcasts/projects/{pid}/render",
            json={"sync": True, "tts_provider": "local"},
        )
        assert rn.status_code == 200, rn.text
        done = rn.json()["project"]
        assert done["status"] == "completed"
        mp4 = paths.media_dir / str(done["output_path"])
        assert mp4.is_file()

        info = probe_video(mp4)
        assert info.width == 1920 and info.height == 1080
        assert info.has_audio is True
        assert info.duration_s >= 5.0

        v_row = query_one(
            paths.db_file, "SELECT qc_json FROM videos WHERE id = ?", (int(done["output_video_id"]),)
        )
        assert v_row is not None
        qc = json.loads(v_row["qc_json"])
        assert qc["passed"] is True

        # Also verify showwaves `cline` mode on 9:16
        cr_wave = client.post(
            "/api/v1/podcasts/projects",
            json={
                "workspace_id": ws_id,
                "title": "Shorts Podcast Clip",
                "aspect_ratio": "9:16",
                "waveform_style": "cline",
                "script_text": "Một góc nhìn ngắn về chất lượng âm thanh chuẩn mười bốn LUFS.\nCùng thử nghiệm bộ lọc sóng nhạc trực tiếp.",
            },
        )
        pid_wave = int(cr_wave.json()["project"]["id"])
        rn_wave = client.post(
            f"/api/v1/podcasts/projects/{pid_wave}/render",
            json={"sync": True, "tts_provider": "local"},
        )
        assert rn_wave.status_code == 200, rn_wave.text
        wave_info = probe_video(paths.media_dir / str(rn_wave.json()["project"]["output_path"]))
        assert wave_info.width == 1080 and wave_info.height == 1920


def test_lipsync_studio_rms_envelope_and_policy(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        ws_strict = int(
            client.post(
                "/api/v1/workspaces",
                json={"name": "Strict Jewelry", "content_policy": "strict_footage"},
            ).json()["workspace"]["id"]
        )
        ws_ai = int(
            client.post(
                "/api/v1/workspaces",
                json={"name": "AI Host Studio", "content_policy": "full_ai"},
            ).json()["workspace"]["id"]
        )

        p_forbid = client.post(
            "/api/v1/lipsync/projects",
            json={
                "workspace_id": ws_strict,
                "title": "Strict Reject",
                "script_text": "Sản phẩm thật không dùng nhân vật nhép môi nhân tạo.",
            },
        ).json()["project"]
        assert (
            client.post(
                f"/api/v1/lipsync/projects/{p_forbid['id']}/render",
                json={"sync": True, "tts_provider": "local"},
            ).status_code
            == 403
        )

        # Create a real portrait PNG via FFmpeg
        portrait_file = tmp_path / "avatar.png"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=0x1e293b:s=540x960:d=1",
                "-vf",
                "drawbox=x=150:y=180:w=240:h=320:color=0xf59e0b@0.8:t=fill,format=rgb24",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                str(portrait_file),
            ],
            allow_creative_filters=True,
        )

        cr = client.post(
            "/api/v1/lipsync/projects",
            json={
                "workspace_id": ws_ai,
                "title": "MC Ảo Điểm Tin",
                "script_text": "Xin chào các bạn đây là bản tin tổng hợp AI chạy hoàn toàn độc lập trên máy cá nhân.",
                "aspect_ratio": "9:16",
            },
        )
        assert cr.status_code == 201
        lid = int(cr.json()["project"]["id"])

        up = client.post(
            f"/api/v1/lipsync/projects/{lid}/upload-portrait",
            files={"file": ("avatar.png", portrait_file.read_bytes(), "image/png")},
        )
        assert up.status_code == 200
        assert up.json()["project"]["portrait_path"].startswith("characters/")

        rn = client.post(
            f"/api/v1/lipsync/projects/{lid}/render",
            json={"sync": True, "tts_provider": "local"},
        )
        assert rn.status_code == 200, rn.text
        done = rn.json()["project"]
        assert done["status"] == "completed"
        assert done["engine_used"] == "ffmpeg_viseme"
        assert done["metrics"]["peak_rms"] > 0.05
        assert done["metrics"]["frames"] >= 20

        mp4 = paths.media_dir / str(done["output_path"])
        assert mp4.is_file()
        info = probe_video(mp4)
        assert info.has_audio is True
        assert info.duration_s >= 5.0

        v_row = query_one(
            paths.db_file, "SELECT qc_json FROM videos WHERE id = ?", (int(done["output_video_id"]),)
        )
        assert v_row is not None
        assert json.loads(v_row["qc_json"])["passed"] is True
