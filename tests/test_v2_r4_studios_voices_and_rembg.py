"""Tests for Stage R4: Real Voices in Podcast/Novel, Consented Channel Voices, Rembg U2Net Cutout & Turn-Synced Host Avatars."""
from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from videocreator.app import create_app
from videocreator.db import get_conn, migrate, query_all, query_one
from videocreator.models_manager import get_local_model, install_local_model
from videocreator.paths import AppPaths, get_paths
from videocreator.pipeline.characters import create_character, cutout_character, save_character_ref_image
from videocreator.pipeline.novel_studio import create_novel_project, render_novel_project
from videocreator.pipeline.podcast_studio import create_podcast_project, render_podcast_project


def _make_speech_like_wav_bytes(duration_s: float = 4.2, sr: int = 24000) -> bytes:
    """Generates a voiced harmonic WAV payload suitable for Channel Voice enrollment tests."""
    import io

    n = int(round(duration_s * sr))
    buf = bytearray(n * 2)
    for i in range(n):
        t = i / sr
        sig = 0.55 * math.sin(2 * math.pi * 185.0 * t) + 0.30 * math.sin(2 * math.pi * 370.0 * t)
        struct.pack_into("<h", buf, i * 2, int(sig * 16000))
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(buf))
    return bio.getvalue()


def _seed_r4_models(target_paths: AppPaths, model_ids: list[str]) -> None:
    default_paths = get_paths()
    migrate(default_paths.db_file, default_paths.migrations_dir)
    migrate(target_paths.db_file, target_paths.migrations_dir)
    for mid in model_ids:
        cached = get_local_model(default_paths, mid)
        if not (cached and cached.get("status") == "ready" and cached.get("installed_on_disk")):
            install_local_model(default_paths, mid, verify_smoke=True)
            cached = get_local_model(default_paths, mid)
        assert cached is not None
        with get_conn(target_paths.db_file) as conn:
            conn.execute(
                "UPDATE local_models SET status = 'ready', smoke_tested = 1, progress = 1.0, local_path = ?, sha256 = ? WHERE model_id = ?",
                (str(cached["local_path"]), str(cached["sha256"]), mid),
            )


@pytest.mark.local
def test_r4_channel_voice_consent_api_and_podcast_avatar_turn_illumination(tmp_path: Path) -> None:
    """Verifies Channel Voice consent enforcement + audit logging, and Podcast host avatar illumination per turn."""
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    wav_bytes = _make_speech_like_wav_bytes(4.5)

    with TestClient(app) as client:
        # 1. Missing consent_confirmed is rejected with 403
        r_denied = client.post(
            "/api/v1/channel-voices",
            files={"file": ("mc.wav", wav_bytes, "audio/wav")},
            data={"name": "Giọng MC", "speaker_name": "Nguyễn Bảo Ngọc", "consent_confirmed": "false"},
        )
        assert r_denied.status_code == 403

        # 2. Consented upload succeeds, binds to character, and writes audit_log
        char_res = client.post(
            "/api/v1/characters",
            json={"workspace_id": 1, "name": "MC Bảo Ngọc"},
        )
        char_id = int(char_res.json()["character"]["id"])

        r_ok = client.post(
            "/api/v1/channel-voices",
            files={"file": ("mc.wav", wav_bytes, "audio/wav")},
            data={
                "name": "Giọng Kênh Bảo Ngọc",
                "speaker_name": "Nguyễn Bảo Ngọc",
                "consent_confirmed": "true",
                "character_id": str(char_id),
            },
        )
        assert r_ok.status_code == 201, r_ok.text
        cv = r_ok.json()["channel_voice"]
        assert cv["voice_token"] == f"channel_voice:{cv['id']}"
        assert cv["duration_s"] >= 3.5

        ch_after = client.get("/api/v1/characters?workspace_id=1").json()["characters"][0]
        assert ch_after["voice_id"] == cv["voice_token"]
        audits = query_all(paths.db_file, "SELECT action FROM audit_log WHERE object_type = 'channel_voice'")
        assert any(a["action"] == "create_channel_voice" for a in audits)

        # 3. Podcast Host Avatar turn-synced illumination verification (fast test_tone mode for -m local)
        pod = create_podcast_project(
            paths,
            workspace_id=1,
            title="Avatar Highlight Check",
            host_a_name="Lan Anh",
            host_b_name="Minh Quân",
            dialogue=[
                {"speaker": "Lan Anh", "text": "Xin chào quý vị khán giả đã quay trở lại chương trình hôm nay."},
                {"speaker": "Minh Quân", "text": "Cảm ơn Lan Anh, hôm nay chúng ta cùng bàn về công nghệ dựng video mới."},
            ],
            aspect_ratio="16:9",
            waveform_style="cline",
        )
        done = render_podcast_project(paths, int(pod["id"]), tts_provider="test_tone")
        assert done["status"] == "completed"
        v_row = query_one(paths.db_file, "SELECT plan_json, output_path FROM videos WHERE id = ?", (done["output_video_id"],))
        assert v_row is not None
        plan = json.loads(str(v_row["plan_json"]))
        turns = plan["turn_windows"]
        layout = plan["avatar_layout"]
        assert len(turns) == 2 and turns[0]["slot"] == "A" and turns[1]["slot"] == "B"

        out_mp4 = paths.media_dir / str(v_row["output_path"])
        cap = cv2.VideoCapture(str(out_mp4))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        av_s = int(layout["size"])
        av_y = int(layout["y"])
        ax = int(layout["host_a_x"])
        bx = int(layout["host_b_x"])

        def _read_avatar_means(time_s: float) -> tuple[float, float]:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(time_s * fps)))
            ok, frm = cap.read()
            assert ok and frm is not None
            mean_a = float(frm[av_y : av_y + av_s, ax : ax + av_s].mean())
            mean_b = float(frm[av_y : av_y + av_s, bx : bx + av_s].mean())
            return mean_a, mean_b

        t0_mid = 0.5 * (float(turns[0]["start_s"]) + float(turns[0]["end_s"]))
        t1_mid = 0.5 * (float(turns[1]["start_s"]) + float(turns[1]["end_s"]))
        a_at_t0, b_at_t0 = _read_avatar_means(t0_mid)
        a_at_t1, b_at_t1 = _read_avatar_means(t1_mid)
        cap.release()

        # Host A is brightly lit on Turn 0 and dims on Turn 1; Host B is dimmed on Turn 0 and lights up on Turn 1!
        assert a_at_t0 > b_at_t0 + 20.0, f"Expected Host A brighter than Host B on Turn 0: A={a_at_t0}, B={b_at_t0}"
        assert b_at_t1 > a_at_t1 + 20.0, f"Expected Host B brighter than Host A on Turn 1: A={a_at_t1}, B={b_at_t1}"


@pytest.mark.models
def test_r4_real_rembg_u2net_cutout_and_vieneu_channel_voice_podcast_and_novel(tmp_path: Path) -> None:
    """Runs real `rembg_u2net` background removal + real `VieNeu-TTS` Channel Voice & Edge TTS in Podcast & Novel."""
    import io

    paths = get_paths(tmp_path / "data")
    _seed_r4_models(paths, ["rembg_u2net", "vieneu_tts_vi"])

    with get_conn(paths.db_file) as conn:
        ws_id = int(
            conn.execute(
                "INSERT INTO workspaces (slug, name, content_policy) VALUES ('r4-studio', 'R4 Studio', 'full_ai')"
            ).lastrowid
        )

    # 1. Real Rembg U2Net foreground segmentation on a non-colorkey gradient background
    img = Image.new("RGB", (320, 320))
    draw = ImageDraw.Draw(img)
    for y in range(320):
        draw.line((0, y, 320, y), fill=(40 + y // 3, 70 + y // 4, 110 + y // 5))
    # High-contrast foreground person/object silhouette in center
    draw.ellipse((110, 55, 210, 155), fill=(245, 215, 190), outline=(20, 20, 20), width=4)
    draw.rounded_rectangle((85, 150, 235, 305), radius=28, fill=(220, 45, 55), outline=(20, 20, 20), width=4)
    bio = io.BytesIO()
    img.save(bio, format="PNG")

    ch = create_character(paths, workspace_id=ws_id, name="Presenter Minh")
    save_character_ref_image(paths, int(ch["id"]), filename="ref.png", data=bio.getvalue())
    cut_ch = cutout_character(paths, int(ch["id"]))
    assert cut_ch["cutout_simulation_flags"] == [], f"Expected real rembg u2net (no fallback): {cut_ch}"
    cut_rgba = np.asarray(Image.open(paths.media_dir / cut_ch["cutout_image_path"]).convert("RGBA"))
    corner_alpha = float(cut_rgba[0:25, 0:25, 3].mean())
    center_alpha = float(cut_rgba[170:250, 130:190, 3].mean())
    assert corner_alpha < 40.0 and center_alpha > 200.0, (
        f"Expected U2Net transparent background & opaque subject: corner={corner_alpha}, center={center_alpha}"
    )

    # 2. Consented Channel Voice synthesized via real VieNeu-TTS v3 Nano in both Podcast & Novel Studios
    from videocreator.pipeline.channel_voices import create_channel_voice

    cv = create_channel_voice(
        paths,
        workspace_id=ws_id,
        name="Giọng Kênh Minh",
        speaker_name="Trần Minh",
        consent_confirmed=True,
        raw_audio_bytes=_make_speech_like_wav_bytes(4.5),
        filename="minh_sample.wav",
        character_id=int(ch["id"]),
    )

    pod = create_podcast_project(
        paths,
        workspace_id=ws_id,
        title="Podcast Giọng Thật",
        host_a_name="Minh",
        host_b_name="Trúc Ly",
        host_a_voice=cv["voice_token"],
        host_b_voice="vieneu:Trúc Ly",
        dialogue=[
            {"speaker": "Minh", "text": "Chào mừng các bạn đến với bản tin sáng nay."},
            {"speaker": "Trúc Ly", "text": "Hôm nay chúng ta có nhiều thông tin rất thú vị."},
        ],
        aspect_ratio="16:9",
        waveform_style="spectrum",
    )
    done_pod = render_podcast_project(paths, int(pod["id"]))
    assert done_pod["status"] == "completed"
    assert "tts_tone_placeholder" not in done_pod["simulation_flags"]

    novel = create_novel_project(
        paths,
        workspace_id=ws_id,
        title="Truyện Ngắn Giọng Kênh",
        source_text="Chương 1: Khởi hành\nBuổi sáng mùa thu nắng dịu nhẹ trên con phố nhỏ.",
        character_id=int(ch["id"]),
    )
    done_novel = render_novel_project(paths, int(novel["id"]))
    assert done_novel["status"] == "completed"
    assert "tts_tone_placeholder" not in done_novel["simulation_flags"]
