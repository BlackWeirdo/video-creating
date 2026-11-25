"""Podcast Studio visual layout, turn-synced illuminating host avatars, and FFmpeg spectrum stage."""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

from videocreator.pipeline.ffmpeg import run_ffmpeg

VALID_WAVEFORM_STYLES: frozenset[str] = frozenset({"bars", "line", "p2p", "cline", "spectrum"})
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean_hex_color(color: str, fallback: str = "#38bdf8") -> str:
    raw = (color or "").strip()
    return raw if _HEX_COLOR_RE.match(raw) else fallback


def hex_to_rgb(hex_col: str) -> tuple[int, int, int]:
    h = clean_hex_color(hex_col).lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_host_avatar_pair(
    out_dir: Path,
    *,
    slot: str,
    host_name: str,
    avatar_path: Path | None,
    size: int,
    accent_rgb: tuple[int, int, int],
) -> tuple[Path, Path]:
    """Renders `(dim_png, active_png)` avatar cards so the speaking host visibly illuminates."""
    dim_png = out_dir / f"host_{slot}_dim.png"
    act_png = out_dir / f"host_{slot}_active.png"

    portrait: Image.Image | None = None
    if avatar_path is not None and avatar_path.is_file():
        try:
            portrait = Image.open(avatar_path).convert("RGB").resize((size - 20, size - 20))
        except Exception:
            portrait = None

    for is_active, dst in ((False, dim_png), (True, act_png)):
        bg_col = (
            (
                min(255, accent_rgb[0] // 2 + 35),
                min(255, accent_rgb[1] // 2 + 45),
                min(255, accent_rgb[2] // 2 + 65),
            )
            if is_active
            else (18, 25, 40)
        )
        border_col = accent_rgb if is_active else (52, 65, 85)
        border_w = 6 if is_active else 2

        card = Image.new("RGB", (size, size), bg_col)
        draw = ImageDraw.Draw(card)

        if portrait is not None:
            factor = 1.12 if is_active else 0.42
            lit = portrait.point(lambda px: max(0, min(255, int(px * factor))))
            card.paste(lit, (10, 10))
        else:
            sil_col = (240, 248, 255) if is_active else (75, 90, 112)
            cx, cy = size // 2, int(size * 0.38)
            r_head = max(12, int(size * 0.17))
            draw.ellipse((cx - r_head, cy - r_head, cx + r_head, cy + r_head), fill=sil_col)
            r_body_x = max(20, int(size * 0.30))
            r_body_y = max(16, int(size * 0.24))
            by_top = cy + r_head + 6
            draw.pieslice(
                (cx - r_body_x, by_top, cx + r_body_x, by_top + r_body_y * 2),
                start=180,
                end=360,
                fill=sil_col,
            )

        if is_active:
            draw.rectangle((2, 2, size - 3, size - 3), outline=border_col, width=border_w)
            draw.rectangle((8, 8, size - 9, size - 9), outline=(255, 255, 255), width=2)
            dot_r = max(5, size // 18)
            draw.ellipse((size - dot_r * 3 - 6, 8, size - 8, 8 + dot_r * 2), fill=(52, 211, 153))
        else:
            draw.rectangle((1, 1, size - 2, size - 2), outline=border_col, width=border_w)

        _ = host_name
        card.save(dst, format="PNG")

    return dim_png, act_png


def build_spectrum_filter(waveform_style: str, width: int, height: int, hex_color: str) -> str:
    col_hex = "0x" + hex_color.lstrip("#")
    if waveform_style in ("bars", "spectrum"):
        ascale = "sqrt" if waveform_style == "spectrum" else "log"
        return (
            f"aformat=channel_layouts=stereo:sample_rates=48000,"
            f"showfreqs=s={width}x{height}:mode=bar:ascale={ascale}:fscale=log:win_size=1024:rate=30:colors={col_hex}|0xa855f7,"
            f"colorkey=0x000000:0.08:0.06,format=yuva420p"
        )
    return (
        f"aformat=channel_layouts=stereo:sample_rates=48000,"
        f"showwaves=s={width}x{height}:mode={waveform_style}:rate=30:colors={col_hex}|0xa855f7,"
        f"colorkey=0x000000:0.08:0.06,format=yuva420p"
    )


def render_podcast_visual_mp4(
    *,
    work_dir: Path,
    speech_wav: Path,
    dur_s: float,
    width: int,
    height: int,
    waveform_style: str,
    hex_col: str,
    host_a_name: str,
    host_b_name: str,
    av_a_file: Path | None,
    av_b_file: Path | None,
    turn_windows: list[tuple[float, float, str]],
) -> tuple[Path, dict[str, int]]:
    """Composites the dark studio backdrop, glowing Host A/B avatars, audio spectrum, and progress bar."""
    wave_w = int(width * 0.80)
    wave_h = max(180, int(height * 0.24))
    wave_x = (width - wave_w) // 2
    wave_y = int(height * 0.46)
    panel_pad = 20

    av_size = max(96, min(int(width * 0.20), int(height * 0.22), 180))
    av_y = max(28, wave_y - panel_pad - av_size - 24)
    av_ax = wave_x + int(wave_w * 0.12)
    av_bx = max(av_ax + av_size + 24, wave_x + wave_w - int(wave_w * 0.12) - av_size)

    dim_a, act_a = render_host_avatar_pair(
        work_dir,
        slot="a",
        host_name=host_a_name,
        avatar_path=av_a_file,
        size=av_size,
        accent_rgb=hex_to_rgb(hex_col),
    )
    dim_b, act_b = render_host_avatar_pair(
        work_dir,
        slot="b",
        host_name=host_b_name,
        avatar_path=av_b_file,
        size=av_size,
        accent_rgb=(192, 132, 252),
    )

    enable_a_terms = [f"between(t,{st:.3f},{en:.3f})" for st, en, sl in turn_windows if sl == "A"]
    enable_b_terms = [f"between(t,{st:.3f},{en:.3f})" for st, en, sl in turn_windows if sl == "B"]
    enable_a = "+".join(enable_a_terms) if enable_a_terms else "0"
    enable_b = "+".join(enable_b_terms) if enable_b_terms else "0"

    spec_filter = build_spectrum_filter(waveform_style, wave_w, wave_h, hex_col)
    col_ff = "0x" + hex_col.lstrip("#")
    bar_y = wave_y + wave_h + 24

    visual_mp4 = work_dir / "podcast_visual.mp4"
    fc = (
        f"[0:v]drawbox=x={wave_x - panel_pad}:y={wave_y - panel_pad}:"
        f"w={wave_w + panel_pad * 2}:h={wave_h + panel_pad * 2}:color=0x1e293b@0.85:t=fill,"
        f"drawbox=x={wave_x - panel_pad}:y={wave_y - panel_pad}:"
        f"w={wave_w + panel_pad * 2}:h={wave_h + panel_pad * 2}:color={col_ff}@0.55:t=3,"
        f"drawbox=x={wave_x}:y={bar_y}:w={wave_w}:h=6:color=0x334155@0.9:t=fill[bg0];"
        f"[bg0][3:v]overlay=x={av_ax}:y={av_y}[bg1];"
        f"[bg1][4:v]overlay=x={av_bx}:y={av_y}[bg2];"
        f"[bg2][5:v]overlay=x={av_ax}:y={av_y}:enable='{enable_a}'[bg3];"
        f"[bg3][6:v]overlay=x={av_bx}:y={av_y}:enable='{enable_b}'[bg4];"
        f"[1:a]{spec_filter}[wave];"
        f"[bg4][wave]overlay=x={wave_x}:y={wave_y}:shortest=1[stage];"
        f"[stage][2:v]overlay=x='{wave_x}+({wave_w}-44)*min(1,t/{dur_s:.3f})':y={bar_y - 2}:shortest=1,"
        f"format=yuv420p[vout]"
    )
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x0b1120:s={width}x{height}:r=30:d={dur_s:.3f}",
            "-i",
            str(speech_wav.resolve()),
            "-f",
            "lavfi",
            "-i",
            f"color=c={col_ff}:s=44x10:r=30:d={dur_s:.3f}",
            "-i",
            str(dim_a.resolve()),
            "-i",
            str(dim_b.resolve()),
            "-i",
            str(act_a.resolve()),
            "-i",
            str(act_b.resolve()),
            "-filter_complex",
            fc,
            "-map",
            "[vout]",
            "-t",
            f"{dur_s:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(visual_mp4.resolve()),
        ],
        allow_creative_filters=True,
    )
    layout = {"size": av_size, "y": av_y, "host_a_x": av_ax, "host_b_x": av_bx}
    return visual_mp4, layout
