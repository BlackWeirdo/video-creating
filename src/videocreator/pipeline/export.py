"""Single multi-platform master MP4 normalizer and cover image extractor (Phase 05, FR-RND-04)."""
from __future__ import annotations

from pathlib import Path

from videocreator.pipeline.ffmpeg import ALLOWED_FILTERS, run_ffmpeg
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.thumbs import extract_thumbnail

__all__ = ["ALLOWED_FILTERS", "extract_cover_frame", "normalize_to_master"]

SOURCE_AUDIO_UNDER = 0.3  # footage sound level under voice-over or music

ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def resolve_canvas_dimensions(aspect_ratio: str | None) -> tuple[int, int]:
    return ASPECT_DIMENSIONS.get((aspect_ratio or "9:16").strip(), (1080, 1920))


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
    mix_source_audio: bool = False,
    width: int = 1080,
    height: int = 1920,
    ducking: bool = True,
    music_volume: float = 0.2,
    sfx_events: list[tuple[Path, float]] | None = None,
) -> float:
    """Normalizes `src_video` into canonical H.264 High / AAC 48kHz stereo master MP4.

    Supports multi-aspect-ratio (`9:16`, `16:9`, `1:1`), `sidechaincompress` music ducking
    under voice-over, transition SFX overlays via `adelay`, and `-14 LUFS` `loudnorm`."""
    info = probe_video(src_video)
    total_dur = max(0.5, info.duration_s)
    fade_start = max(0.0, total_dur - 0.5)
    target_w = int(width) if width > 0 else 1080
    target_h = int(height) if height > 0 else 1920
    clean_music_vol = max(0.02, min(1.0, float(music_volume)))

    dest_master.parent.mkdir(parents=True, exist_ok=True)

    vf_parts: list[str] = []
    if ass_filename:
        # Relative paths only: the subtitles filter mis-parses drive colons and spaces (spike S9).
        fonts_opt = ":fontsdir=fonts" if cwd is not None and (cwd / "fonts").is_dir() else ""
        vf_parts.append(f"subtitles={ass_filename}{fonts_opt}")
    vf_parts.extend(
        [
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease",
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2",
            "setsar=1",
            "fps=30",
            "format=yuv420p",
        ]
    )
    vf_str = ",".join(vf_parts)

    valid_sfx = [
        (p, max(0.0, float(t)))
        for p, t in (sfx_events or [])
        if p.exists() and float(t) < total_dur
    ]
    args: list[str] = ["-i", str(src_video.resolve())]
    af_args: list[str] = []
    with_source = mix_source_audio and info.has_audio
    src_part = (
        f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={SOURCE_AUDIO_UNDER}[src];"
        if with_source
        else ""
    )
    src_label = "[src]" if with_source else ""
    n_src = 1 if with_source else 0

    has_voice = voice_path is not None and voice_path.exists()
    has_music = music_path is not None and music_path.exists()

    if has_voice:
        assert voice_path is not None
        args.extend(["-i", str(voice_path.resolve())])
        args.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
        next_idx = 3
        sfx_chains: list[str] = []
        sfx_labels: list[str] = []

        if has_music:
            assert music_path is not None
            music_idx = next_idx
            next_idx += 1
            args.extend(["-stream_loop", "-1", "-i", str(music_path.resolve())])

            for s_i, (s_path, s_at) in enumerate(valid_sfx):
                args.extend(["-i", str(s_path.resolve())])
                delay_ms = max(0, int(round(s_at * 1000)))
                lbl = f"[sfx{s_i}]"
                sfx_labels.append(lbl)
                sfx_chains.append(
                    f"[{next_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"volume=0.35,adelay={delay_ms}|{delay_ms}{lbl};"
                )
                next_idx += 1

            bed_prep = (
                f"[{music_idx}:a]atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_rates=48000:channel_layouts=stereo,"
                f"volume={clean_music_vol:.3f},afade=t=out:st={fade_start:.3f}:d=0.5[bedraw];"
            )
            if ducking:
                graph = (
                    f"{src_part}"
                    f"[2:a]atrim=0:{total_dur:.3f}[sil];"
                    f"[sil][1:a]amix=inputs=2:duration=first:normalize=0,"
                    f"aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[vkey][vmix];"
                    f"{bed_prep}"
                    f"[bedraw][vkey]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=280:makeup=1[bed];"
                    f"{''.join(sfx_chains)}"
                    f"[vmix][bed]{src_label}{''.join(sfx_labels)}"
                    f"amix=inputs={2 + n_src + len(sfx_labels)}:duration=first:normalize=0,"
                    f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
                )
            else:
                graph = (
                    f"{src_part}{bed_prep}{''.join(sfx_chains)}"
                    f"[2:a][1:a][bedraw]{src_label}{''.join(sfx_labels)}"
                    f"amix=inputs={3 + n_src + len(sfx_labels)}:duration=first:normalize=0,"
                    f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
                )
        else:
            for s_i, (s_path, s_at) in enumerate(valid_sfx):
                args.extend(["-i", str(s_path.resolve())])
                delay_ms = max(0, int(round(s_at * 1000)))
                lbl = f"[sfx{s_i}]"
                sfx_labels.append(lbl)
                sfx_chains.append(
                    f"[{next_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"volume=0.35,adelay={delay_ms}|{delay_ms}{lbl};"
                )
                next_idx += 1
            graph = (
                f"{src_part}{''.join(sfx_chains)}"
                f"[2:a][1:a]{src_label}{''.join(sfx_labels)}"
                f"amix=inputs={2 + n_src + len(sfx_labels)}:duration=first:normalize=0,"
                f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
            )
        args.extend(["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]"])
    elif has_music and with_source:
        assert music_path is not None
        args.extend(["-stream_loop", "-1", "-i", str(music_path.resolve())])
        next_idx = 2
        sfx_chains = []
        sfx_labels = []
        for s_i, (s_path, s_at) in enumerate(valid_sfx):
            args.extend(["-i", str(s_path.resolve())])
            delay_ms = max(0, int(round(s_at * 1000)))
            lbl = f"[sfx{s_i}]"
            sfx_labels.append(lbl)
            sfx_chains.append(
                f"[{next_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                f"volume=0.35,adelay={delay_ms}|{delay_ms}{lbl};"
            )
            next_idx += 1
        graph = (
            f"{src_part}"
            f"[1:a]atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={clean_music_vol:.3f},afade=t=out:st={fade_start:.3f}:d=0.5[bed];"
            f"{''.join(sfx_chains)}"
            f"[bed][src]{''.join(sfx_labels)}amix=inputs={2 + len(sfx_labels)}:duration=first:normalize=0,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        )
        args.extend(["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]"])
    elif has_music:
        assert music_path is not None
        args.extend(["-stream_loop", "-1", "-i", str(music_path.resolve())])
        if valid_sfx:
            sfx_chains = []
            sfx_labels = []
            next_idx = 2
            for s_i, (s_path, s_at) in enumerate(valid_sfx):
                args.extend(["-i", str(s_path.resolve())])
                delay_ms = max(0, int(round(s_at * 1000)))
                lbl = f"[sfx{s_i}]"
                sfx_labels.append(lbl)
                sfx_chains.append(
                    f"[{next_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"volume=0.35,adelay={delay_ms}|{delay_ms}{lbl};"
                )
                next_idx += 1
            graph = (
                f"[1:a]atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_rates=48000:channel_layouts=stereo,"
                f"volume={clean_music_vol:.3f},afade=t=out:st={fade_start:.3f}:d=0.5[bed];"
                f"{''.join(sfx_chains)}"
                f"[bed]{''.join(sfx_labels)}amix=inputs={1 + len(sfx_labels)}:duration=first:normalize=0,"
                f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
            )
            args.extend(["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]"])
        else:
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
