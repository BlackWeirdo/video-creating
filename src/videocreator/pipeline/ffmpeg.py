"""Safe FFmpeg subprocess runner and product-accuracy filter whitelist (Phase 05)."""
from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from pathlib import Path

from videocreator.paths import find_ffmpeg_binary

# BR-PRD-01: Strict whitelist of allowed FFmpeg filters.
# Color grading (eq, curves, lut3d, hue, colorbalance), AI sharpening/upscaling,
# and video speed warping (setpts) are strictly forbidden so silver/gemstone colors remain authentic.
ALLOWED_FILTERS: frozenset[str] = frozenset(
    {
        "scale",
        "pad",
        "crop",
        "setsar",
        "fps",
        "subtitles",
        "ass",
        "split",
        "boxblur",
        "overlay",
        "format",
        "afade",
        "loudnorm",
        "anullsrc",
        "amix",
        "volume",
        "atrim",
        "asetpts",
        "aresample",
        "adelay",
    }
)


class RenderError(RuntimeError):
    """Raised when an FFmpeg render step fails."""


def extract_filter_names(filtergraph: str) -> list[str]:
    """Parses all filter names from an FFmpeg `-vf`, `-af`, or `-filter_complex` expression."""
    cleaned = re.sub(r"\[[^\]]*\]", " ", filtergraph)
    names: list[str] = []
    for chain in cleaned.split(";"):
        for step in chain.split(","):
            token = step.strip()
            if not token:
                continue
            fname = token.split("=", 1)[0].strip()
            if fname:
                names.append(fname)
    return names


def validate_filtergraph_allowed(filtergraph: str) -> None:
    """Raises `ValueError` if `filtergraph` contains any filter outside `ALLOWED_FILTERS` (`BR-PRD-01`)."""
    for fname in extract_filter_names(filtergraph):
        if fname not in ALLOWED_FILTERS:
            raise ValueError(
                f"Forbidden FFmpeg filter '{fname}' violates BR-PRD-01 product accuracy rules. "
                f"Allowed filters: {sorted(ALLOWED_FILTERS)}"
            )


def validate_command_filters(args: list[str]) -> None:
    """Inspects an FFmpeg argument list and validates all `-vf`, `-af`, and `-filter_complex` values."""
    for idx, arg in enumerate(args):
        if arg in ("-vf", "-af", "-filter_complex", "-filter:v", "-filter:a") and idx + 1 < len(args):
            validate_filtergraph_allowed(args[idx + 1])


def check_libass_available() -> bool:
    """Checks that the installed `ffmpeg` binary supports the `subtitles` / `ass` filter."""
    ffmpeg_bin = find_ffmpeg_binary("ffmpeg")
    proc = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    out = proc.stdout or ""
    return " subtitles " in out or " ass " in out


def run_ffmpeg(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: int = 300,
) -> str:
    """Validates filter whitelist and executes `ffmpeg -y <args>` in `cwd`."""
    validate_command_filters(args)
    ffmpeg_bin = find_ffmpeg_binary("ffmpeg")
    cmd = [ffmpeg_bin, "-hide_banner", "-y", *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"FFmpeg timed out after {timeout_s}s") from exc

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or proc.stdout or "Unknown FFmpeg error").strip()[-1200:]
        raise RenderError(f"FFmpeg exited with code {proc.returncode}: {stderr_tail}")

    return (proc.stderr or "").strip()[-1000:]


from videocreator.pipeline.probe import VideoProbeInfo, probe_video  # noqa: E402, F401


