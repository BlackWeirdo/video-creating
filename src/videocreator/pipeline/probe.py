"""Video metadata probing via ffprobe (duration, dimensions, rotation, orientation, fps)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videocreator.paths import find_ffmpeg_binary


class ProbeError(RuntimeError):
    """Raised when ffprobe fails or the file is not a valid video."""


@dataclass(frozen=True)
class VideoProbeInfo:
    duration_s: float
    width: int
    height: int
    fps: float
    rotation: int
    orientation: str  # "portrait" | "landscape" | "square"
    video_codec: str
    audio_codec: str | None
    size_bytes: int

    @property
    def short_edge(self) -> int:
        return min(self.width, self.height)

    @property
    def is_low_res(self) -> bool:
        return self.short_edge < 1080

    @property
    def is_landscape(self) -> bool:
        return self.orientation == "landscape"

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_codec)


def _parse_frame_rate(raw: str) -> float:
    if not raw or raw == "0/0":
        return 0.0
    if "/" in raw:
        num_s, den_s = raw.split("/", 1)
        try:
            num = float(num_s)
            den = float(den_s)
            return round(num / den, 3) if den != 0 else 0.0
        except ValueError:
            return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _extract_rotation(video_stream: dict) -> int:
    tags = video_stream.get("tags") or {}
    if "rotate" in tags:
        try:
            return int(float(tags["rotate"])) % 360
        except (ValueError, TypeError):
            pass
    for side in video_stream.get("side_data_list") or []:
        if "rotation" in side:
            try:
                return int(float(side["rotation"])) % 360
            except (ValueError, TypeError):
                pass
    return 0


def probe_duration(media_path: Path, timeout_s: float = 30.0) -> float:
    """Returns the container duration in seconds of any media file (audio-only included)."""
    cmd = [
        find_ffmpeg_binary("ffprobe"), "-v", "error",
        "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(media_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL
        )
        return float(proc.stdout.strip())
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        raise ProbeError(f"ffprobe could not read duration of {media_path.name}") from exc


def probe_video(video_path: Path, timeout_s: float = 30.0) -> VideoProbeInfo:
    if not video_path.exists():
        raise ProbeError(f"Video file does not exist: {video_path}")

    ffprobe_bin = find_ffmpeg_binary("ffprobe")
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,tags:stream_side_data=rotation",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out on {video_path.name}") from exc
    except OSError as exc:
        raise ProbeError(f"Failed to execute ffprobe: {exc}") from exc

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip()[-500:]
        raise ProbeError(f"ffprobe failed (code {proc.returncode}): {stderr_tail}")

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError("ffprobe output is not valid JSON") from exc

    streams = payload.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video_stream is None:
        raise ProbeError(f"No video stream found in {video_path.name}")

    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = payload.get("format") or {}

    raw_w = int(video_stream.get("width") or 0)
    raw_h = int(video_stream.get("height") or 0)
    if raw_w <= 0 or raw_h <= 0:
        raise ProbeError(f"Invalid video dimensions ({raw_w}x{raw_h})")

    rotation = _extract_rotation(video_stream)
    if rotation in (90, 270):
        eff_w, eff_h = raw_h, raw_w
    else:
        eff_w, eff_h = raw_w, raw_h

    if eff_h > eff_w:
        orientation = "portrait"
    elif eff_w > eff_h:
        orientation = "landscape"
    else:
        orientation = "square"

    duration_s = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
    if duration_s <= 0:
        raise ProbeError(f"Video duration must be positive (got {duration_s})")

    fps = _parse_frame_rate(
        str(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/0")
    )
    if fps <= 0:
        fps = _parse_frame_rate(str(video_stream.get("r_frame_rate") or "30/1"))

    size_bytes = int(fmt.get("size") or video_path.stat().st_size)

    return VideoProbeInfo(
        duration_s=round(duration_s, 3),
        width=eff_w,
        height=eff_h,
        fps=fps,
        rotation=rotation,
        orientation=orientation,
        video_codec=str(video_stream.get("codec_name") or ""),
        audio_codec=str(audio_stream.get("codec_name")) if audio_stream else None,
        size_bytes=size_bytes,
    )
