"""Platform preflight validator (`ffprobe` check against `[platform_limits]` in `config.toml`, Phase 05)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from videocreator.config import PlatformLimitConfig, Settings
from videocreator.paths import find_ffmpeg_binary


def _parse_fps(rate_str: str) -> float:
    if not rate_str or rate_str == "0/0":
        return 0.0
    if "/" in rate_str:
        num_s, den_s = rate_str.split("/", 1)
        try:
            den = float(den_s)
            return round(float(num_s) / den, 2) if den != 0 else 0.0
        except ValueError:
            return 0.0
    try:
        return round(float(rate_str), 2)
    except ValueError:
        return 0.0


def inspect_master_streams(video_path: Path) -> dict[str, Any]:
    """Runs `ffprobe` and returns detailed video/audio stream metadata for preflight checks."""
    ffprobe_bin = find_ffmpeg_binary("ffprobe")
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,sample_rate,channels",
        "-of",
        "json",
        str(video_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video_path}: {proc.stderr}")

    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format") or {}
    streams = data.get("streams") or []

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration_s = float(fmt.get("duration") or 0.0)
    size_bytes = int(fmt.get("size") or video_path.stat().st_size)
    size_mb = round(size_bytes / (1024 * 1024), 3)
    width = int(v_stream.get("width") or 0)
    height = int(v_stream.get("height") or 0)
    fps = _parse_fps(str(v_stream.get("avg_frame_rate") or v_stream.get("r_frame_rate") or "0/0"))

    return {
        "width": width,
        "height": height,
        "duration_s": round(duration_s, 3),
        "size_mb": size_mb,
        "fps": fps,
        "video_codec": str(v_stream.get("codec_name") or "").lower(),
        "pix_fmt": str(v_stream.get("pix_fmt") or "").lower(),
        "has_audio": a_stream is not None,
        "audio_codec": str((a_stream or {}).get("codec_name") or "").lower(),
        "audio_sample_rate": int((a_stream or {}).get("sample_rate") or 0),
        "audio_channels": int((a_stream or {}).get("channels") or 0),
    }


def check_platform(
    video_path: Path,
    platform: str,
    limit: PlatformLimitConfig,
) -> list[str]:
    """Returns a list of Vietnamese preflight error messages for `platform` (empty if valid)."""
    if not video_path.exists():
        return [f"Không tìm thấy file video xuất ({video_path.name})"]

    meta = inspect_master_streams(video_path)
    errors: list[str] = []

    dur = float(meta["duration_s"])
    if dur < limit.min_duration_s:
        errors.append(
            f"Không đăng được {platform}: ngắn hơn {limit.min_duration_s:.1f}s (hiện tại {dur:.1f}s)"
        )
    if dur > limit.max_duration_s:
        errors.append(
            f"Không đăng được {platform}: dài quá {limit.max_duration_s:.1f}s (hiện tại {dur:.1f}s)"
        )

    if float(meta["size_mb"]) > limit.max_size_mb:
        errors.append(
            f"Không đăng được {platform}: dung lượng vượt {limit.max_size_mb:.1f} MB (hiện tại {meta['size_mb']:.1f} MB)"
        )

    w = int(meta["width"])
    h = int(meta["height"])
    ratio = limit.aspect_ratio.strip().lower()
    if w <= 0 or h <= 0:
        errors.append(f"Không đăng được {platform}: kích thước khung hình không hợp lệ ({w}x{h})")
    elif ratio == "9:16" and abs((w / h) - (9 / 16)) > 0.02:
        errors.append(f"Không đăng được {platform}: tỉ lệ khung hình {w}x{h} không phải 9:16")
    elif ratio == "16:9" and abs((w / h) - (16 / 9)) > 0.02:
        errors.append(f"Không đăng được {platform}: tỉ lệ khung hình {w}x{h} không phải 16:9")
    elif ratio == "1:1" and abs((w / h) - 1.0) > 0.02:
        errors.append(f"Không đăng được {platform}: tỉ lệ khung hình {w}x{h} không phải 1:1")
    elif ratio == "any":
        actual = w / h
        if min(abs(actual - (9 / 16)), abs(actual - (16 / 9)), abs(actual - 1.0)) > 0.03:
            errors.append(
                f"Không đăng được {platform}: tỉ lệ khung hình {w}x{h} không khớp 9:16, 16:9 hoặc 1:1"
            )

    fps = float(meta["fps"])
    if fps < limit.min_fps - 0.5 or fps > limit.max_fps + 0.5:
        errors.append(
            f"Không đăng được {platform}: tốc độ khung hình {fps} fps ngoài khoảng {limit.min_fps}-{limit.max_fps} fps"
        )

    if meta["video_codec"] != limit.video_codec.lower():
        errors.append(
            f"Không đăng được {platform}: codec hình '{meta['video_codec']}' khác '{limit.video_codec}'"
        )

    if not meta["has_audio"] or meta["audio_codec"] != limit.audio_codec.lower():
        errors.append(
            f"Không đăng được {platform}: thiếu track âm thanh chuẩn '{limit.audio_codec}'"
        )

    return errors


def check_all_platforms(video_path: Path, settings: Settings) -> dict[str, list[str]]:
    """Runs `check_platform` across all configured platforms (`facebook`, `instagram`, `threads`, `tiktok`)."""
    results: dict[str, list[str]] = {}
    for platform, limit in settings.platform_limits.items():
        results[platform] = check_platform(video_path, platform, limit)
    return results
