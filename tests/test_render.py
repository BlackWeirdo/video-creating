"""Real FFmpeg 9:16 render, ASS subtitle burn, landscape blur-pad, music mix, and preflight tests (Phase 05)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from videocreator.api.routes_assets import import_audio_asset
from videocreator.config import PlatformLimitConfig, load_settings
from videocreator.db import get_conn, migrate, query_one
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import (
    RenderError,
    check_libass_available,
    run_ffmpeg,
    validate_filtergraph_allowed,
)
from videocreator.pipeline.footage_import import import_footage_file
from videocreator.pipeline.preflight import check_all_platforms, check_platform, inspect_master_streams
from videocreator.pipeline.render import render_video
from videocreator.pipeline.render_inputs import build_segment_filter_args
from videocreator.products import create_product

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CLIP_PORTRAIT = SAMPLES_DIR / "clip1_6s.mp4"
CLIP_LANDSCAPE = SAMPLES_DIR / "clip_landscape_5s.mp4"


@pytest.mark.local
def test_filter_whitelist_and_landscape_blur_pad_rules() -> None:
    assert check_libass_available() is True

    # Allowed filters pass
    validate_filtergraph_allowed(
        "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    )

    # Forbidden color grading or speed change filters raise ValueError (BR-PRD-01)
    with pytest.raises(ValueError, match="BR-PRD-01"):
        validate_filtergraph_allowed("scale=1080:1920,eq=contrast=1.2:saturation=1.4")

    with pytest.raises(ValueError, match="BR-PRD-01"):
        validate_filtergraph_allowed("setpts=0.5*PTS,scale=1080:1920")

    # Landscape default uses blur_pad (boxblur + overlay), never center-crop (BR-PRD-03)
    blur_args = build_segment_filter_args(
        orientation="landscape",
        width=1280,
        height=720,
        crop_cfg={"mode": "blur_pad", "x_offset_ratio": 0.5},
    )
    assert blur_args[0] == "-filter_complex"
    assert "boxblur" in blur_args[1]
    assert "overlay" in blur_args[1]
    validate_filtergraph_allowed(blur_args[1])


@pytest.mark.local
def test_real_ffmpeg_render_master_spec_music_and_preflight(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    pid = create_product(
        paths.db_file,
        name="Nhẫn Bạc Xúc Xắc",
        material="Bạc S925",
        facts={"stone": "Không đính đá"},
    )
    fid_p = import_footage_file(
        paths, CLIP_PORTRAIT, product_ids=[pid], enqueue_analysis=False
    )
    fid_l = import_footage_file(
        paths, CLIP_LANDSCAPE, product_ids=[pid], enqueue_analysis=False
    )

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, has_product, product_ids_json)
            VALUES
                (101, ?, 1, 0.2, 3.2, 'Cận cảnh nhẫn dọc', 1, ?),
                (102, ?, 1, 0.5, 3.0, 'Cảnh ngang nền mờ', 1, ?)
            """,
            (fid_p, f"[{pid}]", fid_l, f"[{pid}]"),
        )

    # Generate a real 8-second stereo WAV music file and import it into assets
    music_wav = tmp_path / "bg_music.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            "8.0",
            str(music_wav),
        ]
    )
    asset_id = import_audio_asset(paths, music_wav, kind="music", title="Test Ambient")
    assert asset_id >= 1

    plan = {
        "formula": "hook-first",
        "title": "Nhẫn Xúc Xắc Thủ Công",
        "voice_lang": "vi",
        "caption_lang": "vi",
        "product_ids": [pid],
        "shots": [
            {"shot_id": 101, "start_s": 0.2, "duration_s": 3.0, "text": "Nhẫn bạc S925 chạm khắc thủ công"},
            {"shot_id": 102, "start_s": 0.5, "duration_s": 2.5, "text": "Hoàn thiện tỉ mỉ từng đường nét"},
        ],
        "captions": {
            "facebook": {"text": "FB", "hashtags": ["#bac925"]},
            "instagram": {"text": "IG", "hashtags": ["#bac925"]},
            "threads": {"text": "TH", "hashtags": ["#bac925"]},
            "tiktok": {"text": "TT", "hashtags": ["#bac925"]},
        },
    }

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (footage_id, product_ids_json, engine, status, plan_json)
            VALUES (?, ?, 'ffmpeg', 'planned', ?)
            """,
            (fid_p, f"[{pid}]", json.dumps(plan, ensure_ascii=False)),
        )
        video_id = int(cur.lastrowid or 0)

    summary = render_video(paths, video_id, preset="ultrafast", music_asset_id=asset_id)
    assert "Rendered video" in summary

    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    assert v_row is not None
    assert v_row["status"] == "pending_approval"

    master_file = paths.media_dir / str(v_row["output_path"])
    cover_file = paths.media_dir / str(v_row["cover_path"])
    assert master_file.exists() and master_file.stat().st_size > 5_000
    assert cover_file.exists() and cover_file.stat().st_size > 500

    meta = inspect_master_streams(master_file)
    assert meta["width"] == 1080
    assert meta["height"] == 1920
    assert meta["video_codec"] == "h264"
    assert meta["pix_fmt"] == "yuv420p"
    assert abs(meta["fps"] - 30.0) < 0.5
    assert meta["has_audio"] is True
    assert meta["audio_codec"] == "aac"
    assert meta["audio_sample_rate"] == 48000
    assert meta["audio_channels"] == 2
    assert abs(meta["duration_s"] - 5.5) < 0.25

    settings = load_settings(paths.config_file)
    preflight = check_all_platforms(master_file, settings)
    for plat, errs in preflight.items():
        assert errs == [], f"Unexpected preflight errors for {plat}: {errs}"

    # Verify preflight catches duration limit violation
    strict_limit = PlatformLimitConfig(min_duration_s=1.0, max_duration_s=4.0)
    errs_strict = check_platform(master_file, "tiktok", strict_limit)
    assert len(errs_strict) == 1
    assert "dài quá 4.0s" in errs_strict[0]


@pytest.mark.local
def test_render_nonexistent_shot_marks_video_failed(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    bad_plan = {
        "formula": "hook-first",
        "title": "Missing Shot",
        "shots": [{"shot_id": 9999, "start_s": 0.0, "duration_s": 3.0, "text": "Lỗi"}],
    }
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (product_ids_json, engine, status, plan_json)
            VALUES ('[]', 'ffmpeg', 'planned', ?)
            """,
            (json.dumps(bad_plan),),
        )
        bad_vid = int(cur.lastrowid or 0)

    with pytest.raises(RenderError, match="Shot #9999"):
        render_video(paths, bad_vid)

    row = query_one(paths.db_file, "SELECT status, error FROM videos WHERE id = ?", (bad_vid,))
    assert row is not None
    assert row["status"] == "failed"
    assert "9999" in str(row["error"])


def _mean_volume_db(media: Path) -> float:
    """Mean loudness of the first audio track, measured with FFmpeg's volumedetect."""
    import re
    import subprocess

    from videocreator.paths import find_ffmpeg_binary

    proc = subprocess.run(
        [find_ffmpeg_binary("ffmpeg"), "-hide_banner", "-i", str(media), "-map", "0:a:0",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", proc.stderr)
    assert match, proc.stderr[-500:]
    return float("-inf") if match.group(1) == "-inf" else float(match.group(1))


@pytest.mark.local
def test_keep_original_audio_mixes_footage_sound_and_pads_silent_shots(tmp_path: Path) -> None:
    from videocreator.config import save_settings

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    pid = create_product(paths.db_file, name="Nhẫn Bạc", material="Bạc S925", facts={})

    # A second clip without any audio track, made with real FFmpeg from a sample
    silent_clip = tmp_path / "no_audio.mp4"
    run_ffmpeg(["-i", str(CLIP_LANDSCAPE.resolve()), "-an", "-c:v", "copy", str(silent_clip.resolve())])
    fid_sound = import_footage_file(paths, CLIP_PORTRAIT, product_ids=[pid], enqueue_analysis=False)
    fid_silent = import_footage_file(paths, silent_clip, product_ids=[pid], enqueue_analysis=False)

    # Silent music bed, so any sound in the master can only come from the footage
    music_wav = tmp_path / "silent_music.wav"
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "8.0", str(music_wav)])
    asset_id = import_audio_asset(paths, music_wav, kind="music", title="Silent")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, has_product, product_ids_json) "
            "VALUES (201, ?, 1, 0.0, 4.0, 'Có tiếng', 1, ?), (202, ?, 1, 0.0, 3.0, 'Không tiếng', 1, ?)",
            (fid_sound, f"[{pid}]", fid_silent, f"[{pid}]"),
        )
    plan = {
        "formula": "hook-first", "title": "Tiếng gốc", "voice_lang": "none", "caption_lang": "vi",
        "product_ids": [pid],
        "shots": [
            {"shot_id": 201, "start_s": 0.0, "duration_s": 3.0, "text": "Tiếng gõ bạc"},
            {"shot_id": 202, "start_s": 0.0, "duration_s": 2.5, "text": "Không có tiếng"},
        ],
        "captions": {},
    }

    def render_with(keep: bool) -> Path:
        cfg = load_settings(paths.config_file)
        cfg.render.keep_original_audio = keep
        save_settings(paths.config_file, cfg)
        with get_conn(paths.db_file) as conn:
            cur = conn.execute(
                "INSERT INTO videos (footage_id, product_ids_json, engine, status, plan_json, voice_lang) "
                "VALUES (?, ?, 'ffmpeg', 'planned', ?, 'none')",
                (fid_sound, f"[{pid}]", json.dumps(plan, ensure_ascii=False)),
            )
            vid = int(cur.lastrowid or 0)
        render_video(paths, vid, preset="ultrafast", music_asset_id=asset_id)
        row = query_one(paths.db_file, "SELECT status, output_path FROM videos WHERE id = ?", (vid,))
        assert row is not None and row["status"] == "pending_approval"
        return paths.media_dir / str(row["output_path"])

    kept = render_with(True)
    meta = inspect_master_streams(kept)
    assert meta["audio_codec"] == "aac" and meta["audio_sample_rate"] == 48000 and meta["audio_channels"] == 2
    assert abs(meta["duration_s"] - 5.5) < 0.25  # the silent-pad segment kept concat length right
    assert _mean_volume_db(kept) > -60.0  # footage sound is audible under the (silent) music

    dropped = render_with(False)
    assert inspect_master_streams(dropped)["has_audio"] is True  # music track, as before
    assert _mean_volume_db(dropped) < -80.0  # option off: no footage sound at all


@pytest.mark.local
def test_normalize_mixes_footage_sound_under_voice_and_music(tmp_path: Path) -> None:
    from videocreator.pipeline.export import normalize_to_master

    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "3.0", str(voice)])
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "8.0", str(music)])

    for with_music in (False, True):
        out = tmp_path / f"master_{with_music}.mp4"
        normalize_to_master(
            CLIP_PORTRAIT, out, voice_path=voice, music_path=music if with_music else None,
            preset="ultrafast", mix_source_audio=True,
        )
        assert inspect_master_streams(out)["audio_codec"] == "aac"
        assert _mean_volume_db(out) > -60.0  # silent voice/music: the sound heard is the footage's
