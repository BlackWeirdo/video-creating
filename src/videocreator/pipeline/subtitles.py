"""ASS subtitle file generator with Vietnamese diacritics and UI safe-zone margins (Phase 05)."""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Bundled OFL font (FR-REN-02). libass loads it through `fontsdir`, no system install needed.
FONT_FAMILY = "Be Vietnam Pro"
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


@dataclass(frozen=True)
class SubtitleEvent:
    start_s: float
    end_s: float
    text: str
    words: tuple[tuple[str, float, float], ...] = ()
    secondary_text: str = ""


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


def hex_to_ass_color(hex_color: str, *, default_alpha: int = 0) -> str:
    """Converts `#RRGGBB` or `#AARRGGBB` CSS hex colors into ASS `&HAABBGGRR` format."""
    cleaned = (hex_color or "").strip().lstrip("#")
    if len(cleaned) == 6:
        r, g, b = cleaned[0:2], cleaned[2:4], cleaned[4:6]
        a = f"{max(0, min(255, int(default_alpha))):02X}"
        return f"&H{a}{b.upper()}{g.upper()}{r.upper()}"
    if len(cleaned) == 8:
        a, r, g, b = cleaned[0:2], cleaned[2:4], cleaned[4:6], cleaned[6:8]
        return f"&H{a.upper()}{b.upper()}{g.upper()}{r.upper()}"
    return "&H00FFFFFF"


def _escape_ass_token(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r", "")
        .replace("\n", r"\N")
    )


def _split_events_into_phrases(
    events: list[SubtitleEvent], *, max_words_per_cue: int = 6
) -> list[SubtitleEvent]:
    """Splits events with per-word timings into compact multi-word cues for crisp karaoke/pop."""
    out: list[SubtitleEvent] = []
    for ev in events:
        if not ev.words or len(ev.words) <= max_words_per_cue:
            out.append(ev)
            continue
        for i in range(0, len(ev.words), max_words_per_cue):
            chunk = ev.words[i : i + max_words_per_cue]
            c_start = float(chunk[0][1])
            c_end = float(chunk[-1][2])
            c_text = " ".join(str(w[0]) for w in chunk).strip()
            if c_text and c_end > c_start:
                out.append(
                    SubtitleEvent(
                        start_s=round(c_start, 3),
                        end_s=round(c_end, 3),
                        text=c_text,
                        words=tuple(chunk),
                        secondary_text=ev.secondary_text if i == 0 else "",
                    )
                )
    return out


def _build_karaoke_text(ev: SubtitleEvent, *, wrap_width: int = 30) -> str:
    if not ev.words:
        words = ev.text.strip().split()
        if not words:
            return ""
        total_cs = max(10, int(round((ev.end_s - ev.start_s) * 100)))
        per_word = max(5, total_cs // len(words))
        parts: list[str] = []
        line_len = 0
        for idx, word in enumerate(words):
            dur_cs = (total_cs - per_word * (len(words) - 1)) if idx == len(words) - 1 else per_word
            dur_cs = max(4, dur_cs)
            tok = _escape_ass_token(word)
            prefix = r"\N" if (line_len > 0 and line_len + len(word) + 1 > wrap_width) else (" " if idx > 0 else "")
            if prefix == r"\N":
                line_len = 0
            parts.append(f"{prefix}{{\\kf{dur_cs}}}{tok}")
            line_len += len(word) + (1 if prefix == " " else 0)
        return "".join(parts)

    parts = []
    line_len = 0
    cursor_s = ev.start_s
    for idx, (word, w_start, w_end) in enumerate(ev.words):
        dur_cs = max(4, int(round(max(0.04, float(w_end) - max(cursor_s, float(w_start))) * 100)))
        cursor_s = max(cursor_s, float(w_end))
        tok = _escape_ass_token(str(word))
        if idx > 0 and line_len + len(str(word)) + 1 > wrap_width:
            prefix = r"\N"
            line_len = 0
        else:
            prefix = " " if idx > 0 else ""
        parts.append(f"{prefix}{{\\kf{dur_cs}}}{tok}")
        line_len += len(str(word)) + (1 if prefix == " " else 0)
    return "".join(parts)


def build_styled_ass(
    events: list[SubtitleEvent],
    preset: dict[str, Any],
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    safe_top_ratio: float = 0.15,
    safe_bottom_ratio: float = 0.25,
    safe_right_ratio: float = 0.12,
    total_duration_s: float | None = None,
) -> str:
    """Generates UTF-8 ASS subtitles honoring Video Style Presets (6 styles + Intro/Outro)."""
    margin_top = max(80, int(round(play_res_y * safe_top_ratio)))
    margin_bottom = max(80, int(round(play_res_y * safe_bottom_ratio)))
    margin_r = max(48, int(round(play_res_x * safe_right_ratio)))
    margin_l = 60

    sub_style = str(preset.get("subtitle_style") or "karaoke_highlight").strip().lower()
    font_name = str(preset.get("font_name") or FONT_FAMILY).strip() or FONT_FAMILY
    font_size = int(preset.get("font_size") or 58)
    if play_res_x > play_res_y:  # 16:9 landscape scales slightly more compactly
        font_size = max(36, int(round(font_size * 0.85)))

    pos = str(preset.get("position") or "bottom").strip().lower()
    alignment = 2
    margin_v = margin_bottom
    if pos == "center":
        alignment = 5
        margin_v = 40
    elif pos == "top":
        alignment = 8
        margin_v = margin_top

    primary_ass = hex_to_ass_color(str(preset.get("primary_color") or "#FFFFFF"))
    highlight_ass = hex_to_ass_color(str(preset.get("highlight_color") or "#FFE082"))
    outline_ass = hex_to_ass_color(str(preset.get("outline_color") or "#141414"))
    box_ass = hex_to_ass_color(str(preset.get("box_color") or "#99121216"))

    # For karaoke \kf sweep: PrimaryColour is filled highlight, SecondaryColour is base text.
    main_primary = highlight_ass if sub_style == "karaoke_highlight" else primary_ass
    main_secondary = primary_ass if sub_style == "karaoke_highlight" else highlight_ass
    border_style = 3 if sub_style == "box_highlight" else 1
    outline_w = 14 if sub_style == "box_highlight" else (2 if sub_style == "minimal_bottom" else 4)
    shadow_w = 0 if sub_style == "box_highlight" else (1 if sub_style == "minimal_bottom" else 2)
    style_outline_col = box_ass if sub_style == "box_highlight" else outline_ass

    intro_size = max(42, font_size + 6)
    sec_size = max(30, int(round(font_size * 0.72)))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font_name},{font_size},{main_primary},{main_secondary},{style_outline_col},{box_ass},-1,0,0,0,100,100,0,0,{border_style},{outline_w},{shadow_w},{alignment},{margin_l},{margin_r},{margin_v},1
Style: NeonGlow,{font_name},{font_size},{highlight_ass},{highlight_ass},{highlight_ass},&H00000000,-1,0,0,0,100,100,0,0,1,6,0,{alignment},{margin_l},{margin_r},{margin_v},1
Style: BilingualSec,{font_name},{sec_size},{highlight_ass},{primary_ass},{outline_ass},{box_ass},0,-1,0,0,100,100,0,0,1,2,1,2,{margin_l},{margin_r},{max(36, margin_bottom - font_size - 10)},1
Style: IntroBanner,{font_name},{intro_size},{highlight_ass},{primary_ass},{outline_ass},{box_ass},-1,0,0,0,100,100,0,0,3,12,0,8,{margin_l},{margin_r},{margin_top},1
Style: OutroBanner,{font_name},{intro_size},{primary_ass},{highlight_ass},{outline_ass},{box_ass},-1,0,0,0,100,100,0,0,3,12,0,5,{margin_l},{margin_r},40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    wrap_w = 42 if play_res_x > play_res_y else 28
    dialogue_lines: list[str] = []

    active_events = (
        _split_events_into_phrases(events, max_words_per_cue=5)
        if sub_style in ("karaoke_highlight", "tiktok_pop")
        else list(events)
    )

    for ev in active_events:
        if not ev.text or not ev.text.strip() or ev.end_s <= ev.start_s:
            continue
        start_str = format_ass_timestamp(ev.start_s)
        end_str = format_ass_timestamp(ev.end_s)

        if sub_style == "karaoke_highlight":
            kara_text = _build_karaoke_text(ev, wrap_width=wrap_w)
            dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},Main,,0,0,0,,{kara_text}")
        elif sub_style == "tiktok_pop":
            escaped = escape_and_wrap_ass_text(ev.text, max_chars_per_line=wrap_w)
            pop_tag = rf"{{\fscx114\fscy114\t(0,130,\fscx100\fscy100)\c{highlight_ass}}}"
            dialogue_lines.append(
                f"Dialogue: 0,{start_str},{end_str},Main,,0,0,0,,{pop_tag}{escaped}"
            )
        elif sub_style == "neon_glow":
            escaped = escape_and_wrap_ass_text(ev.text, max_chars_per_line=wrap_w)
            dialogue_lines.append(
                f"Dialogue: 0,{start_str},{end_str},NeonGlow,,0,0,0,,{{\\blur5}}{escaped}"
            )
            dialogue_lines.append(
                f"Dialogue: 1,{start_str},{end_str},Main,,0,0,0,,{escaped}"
            )
        elif sub_style == "bilingual":
            escaped = escape_and_wrap_ass_text(ev.text, max_chars_per_line=wrap_w)
            dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},Main,,0,0,0,,{escaped}")
            if ev.secondary_text.strip():
                sec_escaped = escape_and_wrap_ass_text(ev.secondary_text, max_chars_per_line=wrap_w + 8)
                dialogue_lines.append(
                    f"Dialogue: 0,{start_str},{end_str},BilingualSec,,0,0,0,,{sec_escaped}"
                )
        else:  # box_highlight | minimal_bottom
            escaped = escape_and_wrap_ass_text(ev.text, max_chars_per_line=wrap_w)
            dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},Main,,0,0,0,,{escaped}")

    max_end_s = total_duration_s if total_duration_s is not None else max(
        (ev.end_s for ev in active_events), default=0.0
    )
    intro_text = str(preset.get("intro_text") or "").strip()
    if intro_text and max_end_s >= 0.8:
        intro_end = format_ass_timestamp(min(1.4, max_end_s))
        intro_escaped = escape_and_wrap_ass_text(intro_text, max_chars_per_line=wrap_w)
        dialogue_lines.append(
            f"Dialogue: 2,0:00:00.00,{intro_end},IntroBanner,,0,0,0,,"
            r"{\fscx108\fscy108\t(0,180,\fscx100\fscy100)}" + intro_escaped
        )

    outro_text = str(preset.get("outro_text") or "").strip()
    if outro_text and max_end_s >= 1.8:
        outro_start = format_ass_timestamp(max(0.0, max_end_s - 1.2))
        outro_end = format_ass_timestamp(max_end_s)
        outro_escaped = escape_and_wrap_ass_text(outro_text, max_chars_per_line=wrap_w)
        dialogue_lines.append(
            f"Dialogue: 2,{outro_start},{outro_end},OutroBanner,,0,0,0,,{outro_escaped}"
        )

    return header + "\n".join(dialogue_lines) + "\n"
