"""Tests for UTF-8 ASS subtitle generation, Vietnamese diacritics, and UI safe-zone margins (Phase 05)."""
from __future__ import annotations

import pytest

from videocreator.pipeline.subtitles import (
    SubtitleEvent,
    build_ass,
    escape_and_wrap_ass_text,
    format_ass_timestamp,
)


@pytest.mark.local
def test_ass_timestamp_and_escaping() -> None:
    assert format_ass_timestamp(0.0) == "0:00:00.00"
    assert format_ass_timestamp(65.432) == "0:01:05.43"

    wrapped = escape_and_wrap_ass_text(
        "Chế tác thủ công nhẫn bạc S925 nguyên khối tại xưởng kim hoàn",
        max_chars_per_line=32,
    )
    assert r"\N" in wrapped
    assert "Chế tác thủ công nhẫn bạc S925" in wrapped


@pytest.mark.local
def test_build_ass_safe_zone_margins_and_dialogues() -> None:
    events = [
        SubtitleEvent(0.0, 2.5, "Cận cảnh nhẫn bạc Xúc Xắc"),
        SubtitleEvent(2.5, 5.5, "Đánh bóng thủ công từng góc cạnh"),
    ]
    ass_text = build_ass(events, safe_bottom_ratio=0.25, safe_right_ratio=0.12)
    assert "PlayResX: 1080" in ass_text
    assert "PlayResY: 1920" in ass_text
    # MarginV = 1920 * 0.25 = 480; MarginR = round(1080 * 0.12) = 130
    assert ",60,130,480,1" in ass_text
    assert "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,Cận cảnh nhẫn bạc Xúc Xắc" in ass_text
    assert "Dialogue: 0,0:00:02.50,0:00:05.50,Default,,0,0,0,,Đánh bóng thủ công từng góc cạnh" in ass_text


@pytest.mark.local
def test_libass_selects_bundled_be_vietnam_pro(tmp_path) -> None:
    """Burns one Vietnamese line with real FFmpeg and checks libass picked the bundled font (FR-REN-02)."""
    import shutil
    import subprocess

    from videocreator.paths import find_ffmpeg_binary
    from videocreator.pipeline.subtitles import FONTS_DIR

    (tmp_path / "sub.ass").write_text(
        build_ass([SubtitleEvent(0.0, 1.0, "Nhẫn bạc chế tác thủ công")]), encoding="utf-8"
    )
    shutil.copytree(FONTS_DIR, tmp_path / "fonts")
    proc = subprocess.run(
        [
            find_ffmpeg_binary("ffmpeg"), "-hide_banner", "-loglevel", "verbose", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=1",
            "-vf", "subtitles=sub.ass:fontsdir=fonts", "-f", "null", "-",
        ],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    selected = [ln for ln in proc.stderr.splitlines() if "fontselect" in ln]
    assert selected and all("BeVietnamPro" in ln.replace(" ", "") for ln in selected), selected
