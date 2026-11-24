"""Shared public assembly helpers across render, editor, batch, localize, and specialized studios."""
from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_one
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import RenderError, run_ffmpeg
from videocreator.pipeline.subtitles import SubtitleEvent

SEED_PALETTE: tuple[tuple[str, str], ...] = (
    ("#0f172a", "#38bdf8"),
    ("#1e1b4b", "#a855f7"),
    ("#132a13", "#34d399"),
    ("#31102f", "#f472b6"),
    ("#1c1917", "#fbbf24"),
    ("#0c4a6e", "#22d3ee"),
)


def load_shot_source(paths: AppPaths, shot_id: int) -> tuple[dict[str, Any], Path]:
    """Return `(shot_row, backing_video_file)` for a shot in the workspace shots library."""
    shot_row = query_one(
        paths.db_file,
        """
        SELECT s.*, f.path AS footage_path, f.orientation, f.width, f.height, f.crop_json,
               a.path AS asset_path
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE s.id = ?
        """,
        (shot_id,),
    )
    if shot_row is None:
        raise RenderError(f"Shot #{shot_id} does not exist in shots library")

    rel_src = shot_row.get("footage_path") or shot_row.get("asset_path")
    if not rel_src:
        raise RenderError(f"Shot #{shot_id} has no backing video file")
    src_file = paths.media_dir / str(rel_src)
    if not src_file.exists():
        raise RenderError(f"Backing video file missing on disk: {src_file}")
    return shot_row, src_file


def save_render_cache(
    paths: AppPaths,
    *,
    video_id: int,
    cut_mp4: Path,
    voice_path: Path | None,
    sub_events: list[SubtitleEvent],
    cut_times_s: list[float],
    music_asset_id: int | None,
    aspect_ratio: str,
    mix_source_audio: bool,
) -> dict[str, Any]:
    """Persist intermediate cut/voice/subtitle cache under `media/render_cache/video_<id>/`."""
    from videocreator.pipeline.render_steps import subtitle_events_to_json

    cache_dir = paths.media_dir / "render_cache" / f"video_{video_id}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_cut = cache_dir / "cut.mp4"
    shutil.copy2(cut_mp4, cached_cut)
    rel_cut = f"render_cache/video_{video_id}/cut.mp4"

    rel_voice = ""
    if voice_path is not None and voice_path.exists():
        cached_voice = cache_dir / "voice.wav"
        shutil.copy2(voice_path, cached_voice)
        rel_voice = f"render_cache/video_{video_id}/voice.wav"

    subs_file = cache_dir / "sub_events.json"
    subs_file.write_text(
        json.dumps(subtitle_events_to_json(sub_events), ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "cut_mp4": rel_cut,
        "voice_wav": rel_voice,
        "sub_events_file": f"render_cache/video_{video_id}/sub_events.json",
        "cut_times_s": cut_times_s,
        "music_asset_id": music_asset_id,
        "aspect_ratio": aspect_ratio,
        "mix_source_audio": bool(mix_source_audio),
    }


def count_workspace_shots(db_file: Path, workspace_id: int) -> int:
    """Count available footage/asset shots belonging to `workspace_id`."""
    row = query_one(
        db_file,
        """
        SELECT COUNT(*) AS c
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
        """,
        (int(workspace_id),),
    )
    return int(row["c"]) if row else 0


def ensure_full_ai_canvas_shot(paths: AppPaths, workspace_id: int, aspect_ratio: str) -> int:
    """Ensure a deterministic non-product canvas b-roll shot exists for `full_ai`/`hybrid_remix` studios."""
    existing = query_one(
        paths.db_file,
        """
        SELECT s.id, a.path
        FROM shots s
        JOIN assets a ON s.asset_id = a.id
        WHERE a.workspace_id = ? AND a.kind = 'broll'
        ORDER BY s.id ASC LIMIT 1
        """,
        (int(workspace_id),),
    )
    if existing and existing.get("path") and (paths.media_dir / str(existing["path"])).exists():
        return int(existing["id"])

    ratio_tag = aspect_ratio.replace(":", "x")
    w, h = (
        (640, 360)
        if aspect_ratio == "16:9"
        else ((480, 480) if aspect_ratio == "1:1" else (360, 640))
    )
    rel_path = f"assets/ai_canvas_ws{workspace_id}_{ratio_tag}.mp4"
    dest = paths.media_dir / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={w}x{h}:r=30:d=5.6",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(dest),
        ]
    )
    with get_conn(paths.db_file) as conn:
        a_id = int(
            conn.execute(
                "INSERT INTO assets (workspace_id, kind, path, duration_s, meta_json) VALUES (?, 'broll', ?, 5.6, '{}')",
                (int(workspace_id), rel_path),
            ).lastrowid
        )
        s_id = int(
            conn.execute(
                "INSERT INTO shots (asset_id, idx, start_s, end_s, description, has_product, quality) VALUES (?, 0, 0.0, 5.4, 'AI Canvas Motion', 0, 4)",
                (a_id,),
            ).lastrowid
        )
    return s_id


def render_styled_still_png(
    dest_png: Path,
    *,
    w: int,
    h: int,
    seed: int,
    overlay_image: Path | None = None,
) -> Path:
    """Render a deterministic seeded studio backdrop PNG with optional centered portrait overlay."""
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    bg_hex, fg_hex = SEED_PALETTE[abs(int(seed)) % len(SEED_PALETTE)]
    box_w = max(80, int(w * 0.72))
    box_h = max(80, int(h * 0.56))
    bx = (w - box_w) // 2
    by = (h - box_h) // 2

    if overlay_image is not None and overlay_image.exists():
        ov_w = max(80, int(w * 0.58))
        ov_h = max(80, int(h * 0.52))
        fc = (
            f"[0:v]drawbox=x={bx}:y={by}:w={box_w}:h={box_h}:color={fg_hex}@0.22:t=fill[bg];"
            f"[1:v]scale={ov_w}:{ov_h}:force_original_aspect_ratio=decrease[char];"
            f"[bg][char]overlay=(W-w)/2:(H-h)/2,format=rgb24[vout]"
        )
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={bg_hex}:s={w}x{h}:d=1",
                "-i",
                str(overlay_image.resolve()),
                "-filter_complex",
                fc,
                "-map",
                "[vout]",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                str(dest_png.resolve()),
            ],
            allow_creative_filters=True,
        )
    else:
        vf = (
            f"drawbox=x={bx}:y={by}:w={box_w}:h={box_h}:color={fg_hex}@0.28:t=fill,"
            f"drawbox=x={bx + 24}:y={by + 24}:w={max(20, box_w - 48)}:h={max(20, box_h - 48)}:color={fg_hex}@0.65:t=4,"
            f"format=rgb24"
        )
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={bg_hex}:s={w}x{h}:d=1",
                "-vf",
                vf,
                "-frames:v",
                "1",
                "-c:v",
                "png",
                str(dest_png.resolve()),
            ],
            allow_creative_filters=True,
        )
    return dest_png


def concat_podcast_turns_padded(
    turn_tracks: list[tuple[Path, str, str, str]],
    dest_wav: Path,
    *,
    min_total_s: float = 5.4,
) -> tuple[Path, list[SubtitleEvent], list[tuple[float, float, str]], float]:
    """Concatenate mono 48kHz PCM turn WAVs with sample-accurate subtitle & host-turn timings."""
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48000
    events: list[SubtitleEvent] = []
    turn_windows: list[tuple[float, float, str]] = []
    cursor_frames = 0
    gap_frames = int(0.18 * sample_rate)

    with wave.open(str(dest_wav), "wb") as out_wf:
        out_wf.setnchannels(1)
        out_wf.setsampwidth(2)
        out_wf.setframerate(sample_rate)

        for idx, (wav_path, speaker, text, host_slot) in enumerate(turn_tracks):
            norm_wav = wav_path.with_name(f"{wav_path.stem}_48k.wav")
            run_ffmpeg(
                [
                    "-i",
                    str(wav_path.resolve()),
                    "-ar",
                    str(sample_rate),
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(norm_wav.resolve()),
                ]
            )
            with wave.open(str(norm_wav), "rb") as in_wf:
                frames = in_wf.readframes(in_wf.getnframes())
                n_frames = len(frames) // 2
                out_wf.writeframes(frames)

            start_s = cursor_frames / sample_rate
            cursor_frames += n_frames
            end_s = cursor_frames / sample_rate
            if end_s > start_s:
                turn_windows.append((round(start_s, 3), round(end_s, 3), host_slot))
            label = f"{speaker}: {text}" if speaker else text
            if label.strip() and end_s > start_s:
                events.append(
                    SubtitleEvent(
                        start_s=round(start_s, 3),
                        end_s=round(end_s, 3),
                        text=label.strip(),
                    )
                )
            if idx < len(turn_tracks) - 1:
                out_wf.writeframes(b"\x00\x00" * gap_frames)
                cursor_frames += gap_frames

        total_frames = cursor_frames
        min_frames = int(round(min_total_s * sample_rate))
        if total_frames < min_frames:
            pad_frames = min_frames - total_frames
            out_wf.writeframes(b"\x00\x00" * pad_frames)
            total_frames = min_frames

    return dest_wav, events, turn_windows, round(total_frames / sample_rate, 3)


def concat_wavs_padded(
    turn_tracks: list[tuple[Path, str, str]],
    dest_wav: Path,
    *,
    min_total_s: float = 5.4,
) -> tuple[Path, list[SubtitleEvent], float]:
    """Concatenate mono 48kHz speech turns and pad up to `min_total_s`."""
    out_wav, events, _tw, dur = concat_podcast_turns_padded(
        [(w, spk, txt, "A") for w, spk, txt in turn_tracks],
        dest_wav,
        min_total_s=min_total_s,
    )
    return out_wav, events, dur
