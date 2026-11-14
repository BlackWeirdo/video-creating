"""Single multi-platform master MP4 normalizer and cover image extractor (Phase 05, FR-RND-04)."""
from __future__ import annotations

from pathlib import Path

from videocreator.pipeline.ffmpeg import ALLOWED_FILTERS, run_ffmpeg
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.thumbs import extract_thumbnail

__all__ = ["ALLOWED_FILTERS", "extract_cover_frame", "normalize_to_master"]


def normalize_to_master(
    src_video: Path,
    dest_master: Path,
    *,
    music_path: Path | None = None,
    voice_path: Path | None = None,
    ass_filename: str | None = None,
    cwd: Path | None = None,
    preset: str = "veryfast",
    crf: int = 18,
) -> float:
    """Normalizes `src_video` into the canonical 1080x1920 30fps H.264 High / AAC 48kHz stereo master MP4."""
    info = probe_video(src_video)
    total_dur = max(0.5, info.duration_s)
    fade_start = max(0.0, total_dur - 0.5)

    dest_master.parent.mkdir(parents=True, exist_ok=True)

    vf_parts: list[str] = []
    if ass_filename:
        # Relative paths only: the subtitles filter mis-parses drive colons and spaces (spike S9).
        fonts_opt = ":fontsdir=fonts" if cwd is not None and (cwd / "fonts").is_dir() else ""
        vf_parts.append(f"subtitles={ass_filename}{fonts_opt}")
    vf_parts.extend(
        [
            "scale=1080:1920:force_original_aspect_ratio=decrease",
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            "setsar=1",
            "fps=30",
            "format=yuv420p",
        ]
    )
    vf_str = ",".join(vf_parts)

    args: list[str] = ["-i", str(src_video.resolve())]
    af_args: list[str] = []

    if voice_path is not None and voice_path.exists():
        # Voice-over on a silent bed as long as the footage, optional music underneath.
        # The footage length always wins: a longer voice is cut by `-t`, never the other way round.
        args.extend(["-i", str(voice_path.resolve())])
        args.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
        graph = "[2:a][1:a]amix=inputs=2:duration=first:normalize=0"
        if music_path is not None and music_path.exists():
            args.extend(["-stream_loop", "-1", "-i", str(music_path.resolve())])
            graph = (
                f"[3:a]atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS,volume=0.2,"
                f"afade=t=out:st={fade_start:.3f}:d=0.5[bed];"
                "[2:a][1:a][bed]amix=inputs=3:duration=first:normalize=0"
            )
        graph += ",loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        args.extend(["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]"])
    elif music_path is not None and music_path.exists():
        args.extend(["-stream_loop", "-1", "-i", str(music_path.resolve())])
        args.extend(["-map", "0:v:0", "-map", "1:a:0"])
        af_str = (
            f"atrim=0:{total_dur:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={fade_start:.3f}:d=0.5,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11"
        )
        af_args = ["-af", af_str]
    elif info.has_audio:
        args.extend(["-map", "0:v:0", "-map", "0:a:0"])
        af_args = ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    else:
        args.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )

    args.extend(
        [
            "-vf",
            vf_str,
            *af_args,
            "-t",
            f"{total_dur:.3f}",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-g",
            "60",
            "-keyint_min",
            "60",
            "-sc_threshold",
            "0",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(dest_master.resolve()),
        ]
    )

    run_ffmpeg(args, cwd=cwd)
    master_info = probe_video(dest_master)
    return master_info.duration_s


def extract_cover_frame(
    master_video: Path,
    dest_cover: Path,
    *,
    at_s: float = 1.0,
) -> Path:
    """Extracts `cover.jpg` at `at_s` (clamped within video duration)."""
    info = probe_video(master_video)
    target_t = min(max(0.0, float(at_s)), max(0.0, info.duration_s - 0.1))
    return extract_thumbnail(master_video, target_t, dest_cover)
