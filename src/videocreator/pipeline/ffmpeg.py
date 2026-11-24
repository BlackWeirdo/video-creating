"""Safe FFmpeg subprocess runner and product-accuracy filter whitelist (Phase 05)."""
from __future__ import annotations

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
        "sidechaincompress",
        "silenceremove",
        "atempo",
        "asplit",
        "aformat",
        "acompressor",
    }
)

# Creative & analysis-only FFmpeg filters used outside BR-PRD-01 product shots
# (local audio DSP separation, reup hardsub removal/anti-dup, synthetic AI canvases).
CREATIVE_REMIX_FILTERS: frozenset[str] = frozenset(
    {
        "pan",
        "highpass",
        "lowpass",
        "hflip",
        "vflip",
        "eq",
        "delogo",
        "drawbox",
        "drawgrid",
        "zoompan",
        "color",
        "silencedetect",
        "nullsink",
        "concat",
        "trim",
        "setpts",
        "hue",
        "unsharp",
        "vignette",
        "colorkey",
        "chromakey",
    }
)


class RenderError(RuntimeError):
    """Raised when an FFmpeg render step fails."""


def _split_top_level(text: str, sep: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    in_quote = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            cur.append(ch)
            cur.append(text[i + 1])
            i += 2
            continue
        if ch == "'":
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth > 0:
                depth -= 1
            elif ch == sep and depth == 0:
                parts.append("".join(cur))
                cur = []
                i += 1
                continue
        cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def extract_filter_names(filtergraph: str) -> list[str]:
    """Parses all filter names from an FFmpeg `-vf`, `-af`, or `-filter_complex` expression."""
    cleaned = re.sub(r"\[[^\]]*\]", " ", filtergraph)
    names: list[str] = []
    for chain in _split_top_level(cleaned, ";"):
        for step in _split_top_level(chain, ","):
            token = step.strip()
            if not token:
                continue
            fname = token.split("=", 1)[0].strip()
            if fname:
                names.append(fname)
    return names


def validate_filtergraph_allowed(
    filtergraph: str,
    *,
    allow_creative_filters: bool = False,
) -> None:
    """Raises `ValueError` if `filtergraph` contains any filter outside allowed whitelist (`BR-PRD-01`)."""
    allowed = ALLOWED_FILTERS | CREATIVE_REMIX_FILTERS if allow_creative_filters else ALLOWED_FILTERS
    for fname in extract_filter_names(filtergraph):
        if fname not in allowed:
            raise ValueError(
                f"Forbidden FFmpeg filter '{fname}' violates BR-PRD-01 product accuracy rules. "
                f"Allowed filters: {sorted(allowed)}"
            )


def validate_command_filters(
    args: list[str],
    *,
    allow_creative_filters: bool = False,
) -> None:
    """Inspects an FFmpeg argument list and validates all `-vf`, `-af`, and `-filter_complex` values."""
    for idx, arg in enumerate(args):
        if arg in ("-vf", "-af", "-filter_complex", "-filter:v", "-filter:a") and idx + 1 < len(args):
            validate_filtergraph_allowed(
                args[idx + 1],
                allow_creative_filters=allow_creative_filters,
            )


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
    allow_creative_filters: bool = False,
) -> str:
    """Validates filter whitelist and executes `ffmpeg -y <args>` in `cwd`."""
    validate_command_filters(args, allow_creative_filters=allow_creative_filters)
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




