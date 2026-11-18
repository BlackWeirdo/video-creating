"""Steps of the FFmpeg render: per-shot 9:16 segments, concatenation, voice-over, subtitles (Phase 05)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from videocreator.config import Settings
from videocreator.db import query_one
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import RenderError, run_ffmpeg
from videocreator.pipeline.probe import probe_duration, probe_video
from videocreator.pipeline.render_inputs import build_segment_filter_args
from videocreator.pipeline.subtitles import FONTS_DIR, SubtitleEvent, build_ass, parse_srt

SUBTITLE_FILENAME = "sub.ass"


def _load_shot_source(paths: AppPaths, shot_id: int) -> tuple[dict[str, Any], Path]:
    """The shot row (with footage framing columns) and its backing video file."""
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


SEGMENT_AUDIO_ARGS: tuple[str, ...] = ("-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k")


def _segment_audio_args(
    filter_args: list[str], src_has_audio: bool, duration_s: float
) -> tuple[list[str], list[str]]:
    """`(extra_inputs, output_args)` giving a segment the source's own sound, or silence of the same
    length when the source has none, so every segment has the same AAC track and `concat -c copy`
    keeps working. A `-filter_complex` video output is mapped automatically; `-vf` needs `-map 0:v:0`."""
    video_map = [] if filter_args[0] == "-filter_complex" else ["-map", "0:v:0"]
    if src_has_audio:
        return [], [*video_map, "-map", "0:a:0", *SEGMENT_AUDIO_ARGS]
    silence = ["-f", "lavfi", "-t", f"{duration_s:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    return silence, [*video_map, "-map", "1:a:0", *SEGMENT_AUDIO_ARGS, "-shortest"]


def cut_shot_segments(
    paths: AppPaths, planned_shots: list[dict[str, Any]], work_dir: Path, *, keep_audio: bool = False
) -> tuple[list[str], list[SubtitleEvent], float]:
    """Step 1: cuts each planned shot into a 1080x1920 30fps segment, without sound unless
    `keep_audio` (then each segment carries the footage sound, or silence when it has none).

    Returns `(segment_file_names, subtitle_events_on_shot_timing, total_duration_s)`."""
    seg_files: list[str] = []
    sub_events: list[SubtitleEvent] = []
    cursor_s = 0.0
    has_audio_by_file: dict[Path, bool] = {}
    for idx, planned in enumerate(planned_shots, start=1):
        shot_row, src_file = _load_shot_source(paths, int(planned.get("shot_id") or 0))
        start_s = max(0.0, float(planned.get("start_s", shot_row["start_s"])))
        duration_s = max(0.5, float(planned.get("duration_s", float(shot_row["end_s"]) - start_s)))
        try:
            crop_cfg = json.loads(shot_row["crop_json"]) if shot_row.get("crop_json") else None
        except Exception:
            crop_cfg = None

        raw_focus = shot_row.get("focus_x")
        focus_x = float(raw_focus) if raw_focus is not None else None
        filter_args = build_segment_filter_args(
            orientation=str(shot_row.get("orientation") or "portrait"),
            width=int(shot_row.get("width") or 1080),
            height=int(shot_row.get("height") or 1920),
            crop_cfg=crop_cfg,
            focus_x=focus_x,
        )

        if keep_audio:
            if src_file not in has_audio_by_file:
                has_audio_by_file[src_file] = probe_video(src_file).has_audio
            extra_inputs, audio_args = _segment_audio_args(filter_args, has_audio_by_file[src_file], duration_s)
        else:
            extra_inputs, audio_args = [], ["-an"]

        seg_name = f"seg_{idx:02d}.mp4"
        seg_path = work_dir / seg_name
        run_ffmpeg(
            [
                "-ss",
                f"{start_s:.3f}",
                "-t",
                f"{duration_s:.3f}",
                "-i",
                str(src_file.resolve()),
                *extra_inputs,
                *filter_args,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "14",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                *audio_args,
                str(seg_path.resolve()),
            ],
            cwd=work_dir,
        )
        seg_files.append(seg_name)

        text_line = str(planned.get("text") or "").strip()
        if text_line:
            sub_events.append(
                SubtitleEvent(
                    start_s=round(cursor_s, 3),
                    end_s=round(cursor_s + duration_s, 3),
                    text=text_line,
                )
            )
        cursor_s += duration_s
    return seg_files, sub_events, cursor_s


def concat_segments(seg_files: list[str], work_dir: Path) -> Path:
    """Step 2: concatenates the segments via the concat demuxer."""
    concat_list = work_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{name}'" for name in seg_files) + "\n",
        encoding="utf-8",
    )
    run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            "concat.txt",
            "-c",
            "copy",
            "cut.mp4",
        ],
        cwd=work_dir,
    )
    return work_dir / "cut.mp4"


def add_voice_over(
    paths: AppPaths,
    video_id: int,
    *,
    script_lines: list[str],
    voice_lang: str,
    work_dir: Path,
    mpt_client: Any,
    video_duration_s: float,
) -> tuple[Any, list[SubtitleEvent] | None]:
    """Step 3: optional voice-over (MoneyPrinterTurbo). With a voice, subtitles follow the voice
    timing instead of the shot timing (`FR-REN-07`).

    Returns `(voice_track, subtitle_events)`; both None when no voice could be made."""
    from videocreator.engines.mpt_engine import add_quality_note, try_voice_with_mpt

    voice_track = try_voice_with_mpt(
        paths,
        video_id,
        script_lines=script_lines,
        voice_lang=voice_lang,
        work_dir=work_dir,
        mpt_client=mpt_client,
    )
    if voice_track is None:
        return None, None
    sub_events = [
        ev for ev in parse_srt(voice_track.srt_path.read_text(encoding="utf-8")) if ev.start_s < video_duration_s
    ]
    voice_dur = probe_duration(voice_track.audio_path)
    if voice_dur > video_duration_s + 0.3:
        add_quality_note(
            paths,
            video_id,
            f"Lời đọc dài {voice_dur:.1f}s nhưng hình chỉ {video_duration_s:.1f}s: phần lời cuối bị cắt, nên rút lời hoặc thêm shot",
        )
    return voice_track, sub_events


def write_subtitle_file(
    sub_events: list[SubtitleEvent],
    settings: Settings,
    work_dir: Path,
    *,
    layout_preset: str = "clean_bottom",
) -> None:
    """Writes the UTF-8 ASS subtitle file and its fonts into `work_dir`."""
    ass_content = build_ass(
        sub_events,
        safe_top_ratio=settings.safe_zone.top,
        safe_bottom_ratio=settings.safe_zone.bottom,
        safe_right_ratio=settings.safe_zone.right,
        layout_preset=layout_preset,
    )
    (work_dir / SUBTITLE_FILENAME).write_text(ass_content, encoding="utf-8")
    shutil.copytree(FONTS_DIR, work_dir / "fonts", dirs_exist_ok=True)
