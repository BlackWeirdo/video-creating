"""Studio audio: per-scene voice-over, cut-point sound effect, one mixed track (Phase 17, FR-STD-06).

Remotion renders the picture only. The voice is synthesised per scene (MoneyPrinterTurbo, like Fast
mode) so each line starts with its scene; music is added by the shared master export.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.engines.mpt_client import MPTClient, MPTClientError
from videocreator.engines.mpt_engine import resolve_voice_for_lang
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration
from videocreator.studio.plan import FPS

logger = logging.getLogger("videocreator.studio.audio")

VOICE_OVERRUN_TOLERANCE_S = 0.25
SFX_VOLUME = 0.35


def synthesize_scene_voices(
    paths: AppPaths,
    session_dir: Path,
    scenes: list[dict[str, Any]],
    voice_lang: str,
    *,
    mpt_client: MPTClient | None = None,
) -> list[Path | None] | None:
    """One voice clip per scene with text, cached by voice + text. Returns None when MPT is unavailable."""
    settings = load_settings(paths.config_file)
    language, voice_name = resolve_voice_for_lang(paths, voice_lang)
    client = mpt_client or MPTClient(base_url=f"http://127.0.0.1:{settings.mpt.port}")
    clips: list[Path | None] = []
    for scene in scenes:
        text = str(scene.get("text") or "").strip()
        if not text:
            clips.append(None)
            continue
        key = hashlib.sha1(f"{voice_name}|{text}".encode("utf-8")).hexdigest()[:16]
        clip_dir = session_dir / "voice" / key
        clip = clip_dir / "voice.mp3"
        if not clip.exists():
            try:
                client.synthesize_voice(script_text=text, voice_name=voice_name, language=language, dest_dir=clip_dir)
            except MPTClientError as exc:
                logger.warning("Studio voice unavailable (%s)", exc)
                return None
        clips.append(clip)
    return clips


def voice_fit_problems(scenes: list[dict[str, Any]], clips: list[Path | None]) -> list[str]:
    """A line that reads longer than its scene would run into the next one."""
    problems: list[str] = []
    for idx, (scene, clip) in enumerate(zip(scenes, clips), start=1):
        if clip is None:
            continue
        voice_s = probe_duration(clip)
        if voice_s > float(scene["duration_s"]) + VOICE_OVERRUN_TOLERANCE_S:
            problems.append(
                f"cảnh {idx}: lời đọc mất {voice_s:.1f}s nhưng cảnh chỉ dài {scene['duration_s']:.1f}s; "
                "rút ngắn lời hoặc kéo dài cảnh (trong khoảng của shot)"
            )
    return problems


def build_audio_track(
    scenes: list[dict[str, Any]],
    clips: list[Path | None] | None,
    sfx_path: Path | None,
    out_wav: Path,
) -> Path | None:
    """Mixes voice clips at their scene starts and the sound effect at every cut. None when there is nothing to mix."""
    inputs: list[tuple[Path, int, float]] = []  # (file, delay_ms, volume)
    for scene, clip in zip(scenes, clips or []):
        if clip is not None:
            inputs.append((clip, round(scene["from_frame"] * 1000 / FPS), 1.0))
    if sfx_path is not None and sfx_path.exists():
        for scene in scenes[1:]:
            inputs.append((sfx_path, round(scene["from_frame"] * 1000 / FPS), SFX_VOLUME))
    if not inputs:
        return None

    args: list[str] = []
    chains: list[str] = []
    for i, (file, delay_ms, volume) in enumerate(inputs):
        args.extend(["-i", str(file.resolve())])
        chains.append(f"[{i}:a]aresample=48000,adelay={delay_ms}:all=1,volume={volume}[a{i}]")
    labels = "".join(f"[a{i}]" for i in range(len(inputs)))
    graph = ";".join(chains) + f";{labels}amix=inputs={len(inputs)}:duration=longest:normalize=0[aout]"
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([*args, "-filter_complex", graph, "-map", "[aout]", "-ac", "2", "-ar", "48000", str(out_wav.resolve())])
    return out_wav
