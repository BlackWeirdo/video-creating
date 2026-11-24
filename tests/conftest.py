"""Pytest configuration and automatic real FFmpeg sample media generation (no mocks)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from videocreator.paths import find_ffmpeg_binary

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


def _run_raw_ffmpeg(args: list[str]) -> None:
    ffmpeg_bin = find_ffmpeg_binary("ffmpeg")
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", *args],
        check=True,
        timeout=60,
    )


def _has_periodic_keyframes(video_path: Path) -> bool:
    ffprobe_bin = find_ffmpeg_binary("ffprobe")
    proc = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=flags",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return False
    keyframes = sum(1 for line in proc.stdout.splitlines() if "K" in line)
    return keyframes >= 2


def _generate_portrait_sample(dest: Path, *, first_src: str, second_src: str, freq: int) -> None:
    """Builds a real 1080x1920 6.0s 30fps H.264 + 48kHz stereo AAC MP4 with a clear scene cut at 3.0s."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_raw_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"{first_src}=s=1080x1920:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            f"{second_src}=s=1080x1920:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:sample_rate=48000:duration=6",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v];[2:a]aformat=channel_layouts=stereo[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-g",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )


def _generate_landscape_sample(dest: Path) -> None:
    """Builds a real 1280x720 5.0s 30fps H.264 + 48kHz stereo AAC landscape MP4."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_raw_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1280x720:r=30:d=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=520:sample_rate=48000:duration=5",
            "-filter_complex",
            "[0:v]format=yuv420p[v];[1:a]aformat=channel_layouts=stereo[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-g",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )


@pytest.fixture(scope="session", autouse=True)
def ensure_sample_videos() -> None:
    """Ensures gitignored `.mp4` sample fixtures exist in `tests/samples/` via real FFmpeg."""
    clip1 = SAMPLES_DIR / "clip1_6s.mp4"
    if not clip1.exists() or not _has_periodic_keyframes(clip1):
        _generate_portrait_sample(clip1, first_src="testsrc2", second_src="smptebars", freq=440)

    clip2 = SAMPLES_DIR / "clip2_6s.mp4"
    if not clip2.exists() or not _has_periodic_keyframes(clip2):
        _generate_portrait_sample(clip2, first_src="rgbtestsrc", second_src="testsrc", freq=660)

    clip_land = SAMPLES_DIR / "clip_landscape_5s.mp4"
    if not clip_land.exists() or not _has_periodic_keyframes(clip_land):
        _generate_landscape_sample(clip_land)
