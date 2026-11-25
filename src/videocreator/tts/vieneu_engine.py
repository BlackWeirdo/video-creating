"""VieNeu-TTS v3 Nano CPU synthesis engine (preset voices & zero-shot reference cloning)."""
from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

from videocreator.ai_models.catalog import get_local_model
from videocreator.paths import AppPaths, get_paths
from videocreator.pipeline.probe import probe_duration
from videocreator.tts.audio_fit import proportional_word_timings, trim_voice_silence
from videocreator.tts.types import SynthesizedTrack, TTSUnavailableError


def resolve_vieneu_model_dir(paths: AppPaths | None = None) -> Path:
    app_paths = paths or get_paths()
    info = get_local_model(app_paths, "vieneu_tts_vi")
    if not (info and info.get("status") == "ready" and info.get("installed_on_disk")):
        raise TTSUnavailableError(
            "Model 'vieneu_tts_vi' chưa cài đặt hoặc chưa vượt qua kiểm thử CPU trong Cài đặt."
        )
    model_dir = Path(str(info["local_path"]))
    return model_dir if model_dir.is_dir() else model_dir.parent


def synthesize_vieneu_single(
    text: str,
    *,
    work_dir: Path,
    voice: str = "Minh Quân",
    ref_audio: Path | None = None,
    paths: AppPaths | None = None,
    stem: str = "vieneu_raw",
    tts_instance: Any = None,
    enrolled_voice: dict[str, Any] | None = None,
) -> SynthesizedTrack:
    """Synthesizes Vietnamese speech on CPU via `V3NanoVieNeuTTS` (preset voice or cloned `ref_audio`)."""
    import numpy as np
    import soundfile as sf

    clean_txt = (text or "").strip()
    if not clean_txt:
        raise TTSUnavailableError("Lời thoại trống, không thể đọc VieNeu-TTS")

    work_dir.mkdir(parents=True, exist_ok=True)
    own_instance = tts_instance is None
    if own_instance:
        from vieneu.v3nano import V3NanoVieNeuTTS

        model_dir = resolve_vieneu_model_dir(paths)
        tts = V3NanoVieNeuTTS(onnx_dir=str(model_dir))
    else:
        tts = tts_instance

    try:
        if enrolled_voice is not None:
            wav_24k = tts.infer(clean_txt, voice=enrolled_voice, apply_watermark=False)
        elif ref_audio is not None and ref_audio.is_file():
            wav_24k = tts.infer(clean_txt, ref_audio=str(ref_audio), apply_watermark=False)
        else:
            preset_name = (voice or "").replace("vieneu:", "").strip() or None
            if preset_name and preset_name not in tts._preset_voices:
                preset_name = None
            wav_24k = tts.infer(clean_txt, voice=preset_name, apply_watermark=False)

        if wav_24k is None or len(wav_24k) < 400:
            raise TTSUnavailableError("VieNeu-TTS sinh âm thanh rỗng")

        raw_24k_wav = work_dir / f"{stem}_24k.wav"
        sf.write(
            str(raw_24k_wav),
            np.clip(wav_24k, -1.0, 1.0),
            int(tts.sample_rate),
            subtype="PCM_16",
        )
        trimmed_wav = trim_voice_silence(raw_24k_wav, work_dir / f"{stem}_trimmed.wav")
        raw_24k_wav.unlink(missing_ok=True)
        dur = probe_duration(trimmed_wav)
        return SynthesizedTrack(
            audio_path=trimmed_wav,
            duration_s=dur,
            word_timings=proportional_word_timings(clean_txt, dur),
            applied_atempo=1.0,
            provider="vieneu",
        )
    except TTSUnavailableError:
        raise
    except Exception as exc:
        raise TTSUnavailableError(f"VieNeu-TTS lỗi tổng hợp giọng: {exc}") from exc
    finally:
        if own_instance:
            tts.close()
            gc.collect()
