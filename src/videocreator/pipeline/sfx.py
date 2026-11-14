"""Optional cut-point SFX audio mixer and alternate aspect ratio exporter (Phase 09, FR-REN-10)."""
from __future__ import annotations

import shutil
from pathlib import Path

from videocreator.pipeline.ffmpeg import run_ffmpeg


def mix_sfx_at_cuts(
    src_video: Path,
    dest_video: Path,
    sfx_path: Path | None,
) -> Path:
    """Mixes a user-supplied SFX audio file at the first cut point if `sfx_path` exists (`FR-REN-10`)."""
    dest_video.parent.mkdir(parents=True, exist_ok=True)
    if sfx_path is None or not sfx_path.exists():
        if src_video.resolve() != dest_video.resolve():
            shutil.copy2(src_video, dest_video)
        return dest_video

    run_ffmpeg(
        [
            "-i",
            str(src_video.resolve()),
            "-i",
            str(sfx_path.resolve()),
            "-filter_complex",
            "[1:a]volume=0.35[sfx];[0:a][sfx]amix=inputs=2:duration=first[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(dest_video.resolve()),
        ]
    )
    return dest_video


def export_square_variant(master_9_16: Path, dest_1_1: Path) -> Path:
    """Exports an optional 1080x1080 (1:1) letterboxed/padded variant from the 9:16 master (`FR-REN-10`)."""
    dest_1_1.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(master_9_16.resolve()),
            "-vf",
            "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "copy",
            str(dest_1_1.resolve()),
        ]
    )
    return dest_1_1
