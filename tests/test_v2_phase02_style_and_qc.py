"""Real SQLite + FFmpeg tests for V2 Phase 02 (Style Engine, TTS, Ducking, Restyle, QC — no mocks)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from videocreator.api.routes_assets import import_audio_asset
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_one
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.footage_import import import_footage_file
from videocreator.pipeline.preflight import inspect_master_streams
from videocreator.pipeline.probe import probe_duration
from videocreator.pipeline.qc import run_video_qc
from videocreator.pipeline.render import render_video
from videocreator.pipeline.restyle import restyle_video
from videocreator.pipeline.styles import (
    create_style_preset,
    delete_style_preset,
    get_style_preset,
    list_style_presets,
    update_style_preset,
)
from videocreator.pipeline.subtitles import FONTS_DIR, SubtitleEvent, build_styled_ass
from videocreator.products import create_product
from videocreator.tts import (
    TTSUnavailableError,
    check_syllable_budget,
    count_syllables,
    synthesize_speech_segments,
)

pytestmark = pytest.mark.local

SAMPLE_CLIP_1 = Path(__file__).resolve().parent / "samples" / "clip1_6s.mp4"


def test_migration_016_and_style_preset_crud(tmp_path: Path) -> None:
    db_file = tmp_path / "phase02_styles.db"
    migrate(db_file)

    presets = list_style_presets(db_file)
    preset_ids = {p["id"] for p in presets}
    assert {
        "tiktok_karaoke",
        "tiktok_pop",
        "box_highlight",
        "neon_glow",
        "minimal_bottom",
        "bilingual_sub",
    }.issubset(preset_ids)

    with pytest.raises(ValueError, match="built-in"):
        delete_style_preset(db_file, "tiktok_karaoke")

    created = create_style_preset(
        db_file,
        name="Phong cách V2 Thương hiệu",
        workspace_id=1,
        subtitle_style="box_highlight",
        highlight_color="#00FFAA",
        intro_text="BẠC S925 CHẾ TÁC TAY",
        outro_text="ĐẶT HÀNG NGAY",
    )
    assert created["subtitle_style"] == "box_highlight"
    assert created["is_builtin"] is False

    updated = update_style_preset(
        db_file,
        created["id"],
        font_size=64,
        music_volume=0.18,
        ducking_enabled=False,
    )
    assert updated["font_size"] == 64
    assert updated["music_volume"] == pytest.approx(0.18)
    assert updated["ducking_enabled"] is False

    delete_style_preset(db_file, created["id"])
    assert get_style_preset(db_file, created["id"]) is None


def test_all_six_styled_ass_presets_burn_with_libass(tmp_path: Path) -> None:
    db_file = tmp_path / "phase02_ass.db"
    migrate(db_file)

    events = [
        SubtitleEvent(
            start_s=0.1,
            end_s=2.4,
            text="Nhẫn bạc thủ công S925 sáng bóng",
            words=(
                ("Nhẫn", 0.1, 0.5),
                ("bạc", 0.5, 0.9),
                ("thủ", 0.9, 1.3),
                ("công", 1.3, 1.7),
                ("S925", 1.7, 2.0),
                ("sáng", 2.0, 2.2),
                ("bóng", 2.2, 2.4),
            ),
            secondary_text="Handcrafted 925 silver ring",
        )
    ]

    presets = {p["subtitle_style"]: p for p in list_style_presets(db_file)}
    assert len(presets) == 6

    rendered_styles = {}
    for style_key, p in presets.items():
        p_with_banners = {
            **p,
            "intro_text": "BẠC THỦ CÔNG",
            "outro_text": "THEO DÕI KÊNH",
        }
        ass_doc = build_styled_ass(
            events,
            p_with_banners,
            total_duration_s=2.8,
        )
        rendered_styles[style_key] = ass_doc
        assert "Style: IntroBanner" in ass_doc
        assert "Dialogue: 2,0:00:00.00" in ass_doc
        assert "Style: OutroBanner" in ass_doc

    assert r"\kf" in rendered_styles["karaoke_highlight"]
    assert r"\fscx114\fscy114" in rendered_styles["tiktok_pop"]
    assert "3,14,0," in rendered_styles["box_highlight"]
    assert r"\blur5" in rendered_styles["neon_glow"]
    assert "BilingualSec" in rendered_styles["bilingual"]

    # Burn 3 key styles onto real video streams with libass to verify syntax & font rendering
    fonts_dir = tmp_path / "fonts"
    shutil.copytree(FONTS_DIR, fonts_dir, dirs_exist_ok=True)
    for style_key in ("karaoke_highlight", "neon_glow", "bilingual"):
        ass_path = tmp_path / f"{style_key}.ass"
        ass_path.write_text(rendered_styles[style_key], encoding="utf-8")
        out_mp4 = tmp_path / f"burn_{style_key}.mp4"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "testsrc2=s=1080x1920:r=30:d=2",
                "-vf",
                f"subtitles={ass_path.name}:fontsdir=fonts,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                str(out_mp4.resolve()),
            ],
            cwd=tmp_path,
        )
        assert out_mp4.exists() and out_mp4.stat().st_size > 2_000


def test_tts_syllable_budget_local_synthesis_silenceremove_and_atempo(tmp_path: Path) -> None:
    assert count_syllables("Nhẫn bạc S925 chế tác thủ công", "vi") == 7
    assert count_syllables("Handcrafted sterling silver ring", "en") >= 4

    budget_ok = check_syllable_budget(
        [{"shot_id": 1, "duration_s": 3.0, "text": "Nhẫn bạc S925 thủ công"}], lang="vi"
    )
    assert budget_ok[0]["over_budget"] is False

    long_line = " ".join(["nhẫn bạc thủ công tinh xảo từng chi tiết"] * 4)
    budget_over = check_syllable_budget(
        [{"shot_id": 1, "duration_s": 2.0, "text": long_line}], lang="vi"
    )
    assert budget_over[0]["over_budget"] is True
    assert 1.0 < budget_over[0]["recommended_atempo"] <= 1.35

    # Local waveform synthesizer trims silence and fits longer line via atempo
    track, warnings = synthesize_speech_segments(
        [(long_line[:60], 2.0)],
        lang="vi",
        voice="local-vi-studio",
        provider_name="local",
        work_dir=tmp_path / "tts_work",
    )
    assert track.audio_path.exists()
    assert track.provider == "local"
    assert track.applied_atempo > 1.0
    assert len(track.word_timings) >= 6
    assert warnings
    assert probe_duration(track.audio_path) <= 4.5

    # Invalid provider cleanly raises TTSUnavailableError
    with pytest.raises(TTSUnavailableError):
        synthesize_speech_segments(
            [("Xin chào", 2.0)],
            lang="vi",
            voice="unknown",
            provider_name="nonexistent_tts",
            work_dir=tmp_path / "tts_bad",
        )


def test_render_v2_with_local_voice_ducking_sfx_aspect_ratios_restyle_and_qc(
    tmp_path: Path,
) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    cfg = load_settings(paths.config_file)
    cfg.voice.vi_provider = "local"
    save_settings(paths.config_file, cfg)

    pid = create_product(paths.db_file, name="Lắc Tay Bạc S925", material="Bạc S925")
    fid = import_footage_file(paths, SAMPLE_CLIP_1, product_ids=[pid], enqueue_analysis=False)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, has_product, product_ids_json)
            VALUES
                (1, ?, 1, 0.0, 2.8, 'Cận cảnh vòng bạc', 1, ?),
                (2, ?, 2, 2.8, 5.6, 'Đeo lên cổ tay', 1, ?)
            """,
            (fid, f"[{pid}]", fid, f"[{pid}]"),
        )

    music_wav = tmp_path / "bgm_tone.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=280:sample_rate=48000:duration=8",
            "-ac",
            "2",
            str(music_wav),
        ]
    )
    music_id = import_audio_asset(paths, music_wav, kind="music", title="Gentle BGM")

    sfx_wav = tmp_path / "whoosh.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=960:sample_rate=48000:duration=0.25",
            "-ac",
            "2",
            str(sfx_wav),
        ]
    )
    sfx_id = import_audio_asset(paths, sfx_wav, kind="sfx", title="Whoosh SFX")

    custom_style = create_style_preset(
        paths.db_file,
        name="Brand Ducking + SFX",
        workspace_id=1,
        subtitle_style="karaoke_highlight",
        ducking_enabled=True,
        music_volume=0.25,
        sfx_transition_asset_id=sfx_id,
        intro_text="MẪU MỚI",
    )

    plan = {
        "formula": "hook-first",
        "title": "Lắc tay bạc S925",
        "voice_lang": "vi",
        "caption_lang": "vi",
        "product_ids": [pid],
        "shots": [
            {"shot_id": 1, "start_s": 0.0, "duration_s": 2.6, "text": "Lắc tay bạc S925 sáng tự nhiên"},
            {"shot_id": 2, "start_s": 2.8, "duration_s": 2.6, "text": "Chế tác tinh xảo từng mắt xích"},
        ],
        "captions": {},
    }

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (
                footage_id, product_ids_json, engine, voice_lang, status,
                plan_json, style_preset, aspect_ratio
            )
            VALUES (?, ?, 'ffmpeg', 'vi', 'planned', ?, ?, '9:16')
            """,
            (fid, f"[{pid}]", json.dumps(plan, ensure_ascii=False), custom_style["id"]),
        )
        vid_portrait = int(cur.lastrowid or 0)

        cur2 = conn.execute(
            """
            INSERT INTO videos (
                footage_id, product_ids_json, engine, voice_lang, status,
                plan_json, style_preset, aspect_ratio
            )
            VALUES (?, ?, 'ffmpeg', 'none', 'planned', ?, 'neon_glow', '16:9')
            """,
            (fid, f"[{pid}]", json.dumps(plan, ensure_ascii=False)),
        )
        vid_wide = int(cur2.lastrowid or 0)

    # Render portrait video with internal local TTS + ducking + SFX + QC
    render_video(paths, vid_portrait, preset="ultrafast", music_asset_id=music_id)
    v1 = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (vid_portrait,))
    assert v1 is not None
    assert v1["status"] == "pending_approval"
    assert v1["style_preset"] == custom_style["id"]
    assert v1["aspect_ratio"] == "9:16"

    master_1 = paths.media_dir / str(v1["output_path"])
    meta_1 = inspect_master_streams(master_1)
    assert (meta_1["width"], meta_1["height"]) == (1080, 1920)
    assert meta_1["video_codec"] == "h264"
    assert meta_1["audio_codec"] == "aac"

    qc_1 = json.loads(str(v1["qc_json"]))
    assert qc_1["passed"] is True, f"QC failed unexpectedly: {qc_1}"
    assert qc_1["integrated_lufs"] is not None
    assert -18.5 <= qc_1["integrated_lufs"] <= -9.5

    cache_1 = json.loads(str(v1["render_cache_json"]))
    assert (paths.media_dir / cache_1["cut_mp4"]).exists()
    assert (paths.media_dir / cache_1["voice_wav"]).exists()
    assert (paths.media_dir / cache_1["sub_events_file"]).exists()

    # Fast restyle reuses cached cut_mp4 + voice_wav to switch style to tiktok_pop
    restyle_msg = restyle_video(
        paths, vid_portrait, "tiktok_pop", music_asset_id=music_id, preset="ultrafast"
    )
    assert "tiktok_pop" in restyle_msg
    v1_restyled = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (vid_portrait,))
    assert v1_restyled is not None
    assert v1_restyled["style_preset"] == "tiktok_pop"
    assert json.loads(str(v1_restyled["qc_json"]))["passed"] is True

    # Render landscape 16:9 video -> must produce true 1920x1080 blur-padded canvas
    render_video(paths, vid_wide, preset="ultrafast", music_asset_id=music_id)
    v2 = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (vid_wide,))
    assert v2 is not None
    meta_2 = inspect_master_streams(paths.media_dir / str(v2["output_path"]))
    assert (meta_2["width"], meta_2["height"]) == (1920, 1080)


def test_qc_detects_black_video_and_silent_audio(tmp_path: Path) -> None:
    broken_mp4 = tmp_path / "broken_black_silent.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(broken_mp4.resolve()),
        ]
    )
    qc = run_video_qc(broken_mp4, expect_voice=True)
    assert qc["passed"] is False
    assert qc["black_duration_s"] >= 2.0
    assert qc["silence_duration_s"] >= 1.5
    assert any("đen" in issue.lower() for issue in qc["issues"])
    assert any("âm thanh" in issue.lower() or "câm" in issue.lower() for issue in qc["issues"])
