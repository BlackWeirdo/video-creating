"""ASS subtitle file generator with Vietnamese diacritics and UI safe-zone margins (Phase 05)."""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass


from pathlib import Path

# Bundled OFL font (FR-REN-02). libass loads it through `fontsdir`, no system install needed.
FONT_FAMILY = "Be Vietnam Pro"
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


@dataclass(frozen=True)
class SubtitleEvent:
    start_s: float
    end_s: float
    text: str


_SRT_TIME = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def parse_srt(srt_text: str) -> list[SubtitleEvent]:
    """Parses SRT cues into subtitle events (used for voice-timed subtitles, `FR-REN-07`)."""
    events: list[SubtitleEvent] = []
    for block in re.split(r"\r?\n\s*\r?\n", srt_text.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        for idx, line in enumerate(lines):
            match = _SRT_TIME.search(line)
            if not match:
                continue
            h1, m1, s1, ms1, h2, m2, s2, ms2 = match.groups()
            start_s = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1.ljust(3, "0")) / 1000
            end_s = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2.ljust(3, "0")) / 1000
            text = " ".join(lines[idx + 1 :])
            if text and end_s > start_s:
                events.append(SubtitleEvent(start_s=start_s, end_s=end_s, text=text))
            break
    return events


def format_ass_timestamp(seconds: float) -> str:
    """Formats seconds into ASS timestamp `H:MM:SS.cc`."""
    clamped = max(0.0, float(seconds))
    total_cs = int(round(clamped * 100))
    hours = total_cs // 360000
    rem = total_cs % 360000
    minutes = rem // 6000
    rem %= 6000
    secs = rem // 100
    cs = rem % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def escape_and_wrap_ass_text(text: str, max_chars_per_line: int = 34) -> str:
    """Escapes ASS control characters and wraps lines cleanly with `\\N`."""
    cleaned = (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", "\n")
        .strip()
    )
    if not cleaned:
        return ""
    wrapped_lines: list[str] = []
    for paragraph in cleaned.split("\n"):
        p = paragraph.strip()
        if not p:
            continue
        lines = textwrap.wrap(
            p,
            width=max_chars_per_line,
            break_long_words=False,
            break_on_hyphens=False,
        )
        wrapped_lines.extend(lines or [p])
    return r"\N".join(wrapped_lines)


def build_ass(
    events: list[SubtitleEvent],
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    safe_bottom_ratio: float = 0.25,
    safe_right_ratio: float = 0.12,
    font_name: str = FONT_FAMILY,
    font_size: int = 56,
) -> str:
    """Builds a complete UTF-8 ASS subtitle document positioned above the bottom 25% UI safe zone."""
    margin_v = max(120, int(round(play_res_y * safe_bottom_ratio)))
    margin_r = max(60, int(round(play_res_x * safe_right_ratio)))
    margin_l = 60

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogue_lines: list[str] = []
    for ev in events:
        if not ev.text or not ev.text.strip():
            continue
        if ev.end_s <= ev.start_s:
            continue
        start_str = format_ass_timestamp(ev.start_s)
        end_str = format_ass_timestamp(ev.end_s)
        escaped = escape_and_wrap_ass_text(ev.text)
        if escaped:
            dialogue_lines.append(
                f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped}"
            )

    return header + "\n".join(dialogue_lines) + "\n"
