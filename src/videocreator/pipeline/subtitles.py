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


def _expand_kinetic_events(events: list[SubtitleEvent]) -> list[SubtitleEvent]:
    """Splits longer lines into 2-3 rhythmic phrase chunks for `kinetic_words` preset."""
    expanded: list[SubtitleEvent] = []
    for ev in events:
        words = ev.text.strip().split()
        dur = ev.end_s - ev.start_s
        if len(words) <= 4 or dur < 1.2:
            expanded.append(ev)
            continue
        chunk_count = 3 if (len(words) >= 9 and dur >= 2.1) else 2
        chunks: list[str] = []
        step = max(1, round(len(words) / chunk_count))
        for i in range(chunk_count):
            start_idx = i * step
            end_idx = len(words) if i == chunk_count - 1 else min(len(words), (i + 1) * step)
            part = " ".join(words[start_idx:end_idx]).strip()
            if part:
                chunks.append(part)
        if len(chunks) <= 1:
            expanded.append(ev)
            continue
        total_chars = max(1, sum(len(c) for c in chunks))
        cursor = ev.start_s
        for idx, chunk in enumerate(chunks):
            piece_dur = (ev.end_s - cursor) if idx == len(chunks) - 1 else round(dur * (len(chunk) / total_chars), 3)
            piece_end = min(ev.end_s, round(cursor + max(0.35, piece_dur), 3))
            if piece_end > cursor:
                expanded.append(SubtitleEvent(start_s=round(cursor, 3), end_s=piece_end, text=chunk))
                cursor = piece_end
    return expanded


def build_ass(
    events: list[SubtitleEvent],
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    safe_top_ratio: float = 0.15,
    safe_bottom_ratio: float = 0.25,
    safe_right_ratio: float = 0.12,
    font_name: str = FONT_FAMILY,
    font_size: int = 56,
    layout_preset: str = "clean_bottom",
) -> str:
    """Builds a complete UTF-8 ASS subtitle document positioned strictly inside the UI safe zone."""
    margin_top = max(140, int(round(play_res_y * safe_top_ratio)))
    margin_v = max(120, int(round(play_res_y * safe_bottom_ratio)))
    margin_r = max(60, int(round(play_res_x * safe_right_ratio)))
    margin_l = 60

    preset = (layout_preset or "clean_bottom").strip().lower()
    active_events = _expand_kinetic_events(events) if preset == "kinetic_words" else list(events)
    hook_size = max(font_size + 14, 68)
    top_size = max(font_size + 6, 60)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,{margin_l},{margin_r},{margin_v},1
Style: HookCenter,{font_name},{hook_size},&H00D8F3FF,&H000000FF,&H00101014,&H90000000,-1,0,0,0,100,100,1,0,1,5,3,5,{margin_l},{margin_r},{margin_v},1
Style: HookTop,{font_name},{top_size},&H00FFFFFF,&H000000FF,&H99121216,&H99121216,-1,0,0,0,100,100,0,0,3,14,0,8,{margin_l},{margin_r},{margin_top},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogue_lines: list[str] = []
    first_emitted = False
    for ev in active_events:
        if not ev.text or not ev.text.strip():
            continue
        if ev.end_s <= ev.start_s:
            continue
        start_str = format_ass_timestamp(ev.start_s)
        end_str = format_ass_timestamp(ev.end_s)
        wrap_width = 24 if (not first_emitted and preset in ("big_center_title", "top_banner")) else 34
        escaped = escape_and_wrap_ass_text(ev.text, max_chars_per_line=wrap_width)
        if not escaped:
            continue

        style_name = "Default"
        anim_tag = ""
        if not first_emitted and ev.start_s <= 2.5:
            if preset == "big_center_title":
                style_name = "HookCenter"
                anim_tag = r"{\fscx108\fscy108\t(0,180,\fscx100\fscy100)}"
            elif preset == "top_banner":
                style_name = "HookTop"
        if preset == "kinetic_words" and not anim_tag:
            anim_tag = r"{\fscx107\fscy107\t(0,130,\fscx100\fscy100)}"

        first_emitted = True
        dialogue_lines.append(
            f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{anim_tag}{escaped}"
        )

    return header + "\n".join(dialogue_lines) + "\n"
