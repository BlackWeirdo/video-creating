"""Frames a rendered video is scored from: the hook seconds plus one frame per shot (`FR-APR-05`).

An image-only model (Claude) cannot watch the video, so it gets these frames in time order;
a video model (Gemini) receives the whole file and ignores them.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from videocreator.pipeline.thumbs import ThumbnailError, extract_thumbnail

logger = logging.getLogger("videocreator.pipeline.quality")

HOOK_TIMES_S: tuple[float, ...] = (0.3, 1.3, 2.3)  # 0.3 s skips a black first frame
MAX_FRAMES = 12
MIN_GAP_S = 0.5
FALLBACK_SHOT_FRAMES = 6


def frame_times(plan: dict[str, Any], duration_s: float) -> list[float]:
    """Sorted timestamps: hook frames, then the middle of each planned shot; near-duplicates dropped."""
    last_t = max(0.0, duration_s - 0.05)
    mids: list[float] = []
    cursor = 0.0
    for shot in plan.get("shots") or []:
        try:
            dur = float(shot.get("duration_s") or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        if dur > 0:
            mids.append(round(cursor + dur / 2.0, 2))
            cursor += dur
    if not mids and duration_s > 0:  # no plan timing: spread frames over the video
        step = duration_s / (FALLBACK_SHOT_FRAMES + 1)
        mids = [round(step * (i + 1), 2) for i in range(FALLBACK_SHOT_FRAMES)]
    room = MAX_FRAMES - len(HOOK_TIMES_S)
    if len(mids) > room:  # many shots: keep an even spread
        mids = [mids[round(i * (len(mids) - 1) / (room - 1))] for i in range(room)]

    chosen: list[float] = []
    for t in [*HOOK_TIMES_S, *mids]:
        t = min(t, last_t)
        if all(abs(t - c) >= MIN_GAP_S for c in chosen):
            chosen.append(t)
    return sorted(chosen)[:MAX_FRAMES]


def extract_score_frames(video: Path, times: list[float], work_dir: Path) -> list[tuple[float, Path]]:
    """Extracts one JPG per timestamp into `work_dir`; frames that fail are skipped."""
    work_dir.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[float, Path]] = []
    for idx, t in enumerate(times, start=1):
        dest = work_dir / f"frame_{idx:02d}.jpg"
        try:
            frames.append((t, extract_thumbnail(video, t, dest)))
        except ThumbnailError as exc:
            logger.info("Score frame at %.2fs skipped for %s: %s", t, video.name, exc)
    return frames
