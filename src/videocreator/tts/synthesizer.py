"""Multi-engine TTS coordinator (`edge_engine`, `vieneu_engine`, `local_waveform`, `audio_fit`)."""
from __future__ import annotations

import gc
import logging
import shutil
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.pipeline.probe import probe_duration
from videocreator.tts.audio_fit import fit_voice_to_budget, trim_voice_silence
from videocreator.tts.edge_engine import synthesize_edge_python_or_cli
from videocreator.tts.local_waveform import synthesize_local_waveform
from videocreator.tts.types import SynthesizedTrack, TTSUnavailableError, WordTiming
from videocreator.tts.vieneu_engine import resolve_vieneu_model_dir, synthesize_vieneu_single

logger = logging.getLogger("videocreator.tts.synthesizer")


def synthesize_speech_segments(
    lines: list[tuple[str, float]],
    *,
    lang: str,
    voice: str,
    provider_name: str,
    work_dir: Path,
    max_atempo: float = 1.35,
    ref_audio: Path | None = None,
    paths: AppPaths | None = None,
) -> tuple[SynthesizedTrack, list[str]]:
    """Synthesizes continuous voice-over from `(text, shot_duration_s)` tuples and fits duration."""
    non_empty = [(t.strip(), float(d)) for t, d in lines if t and t.strip()]
    if not non_empty:
        raise TTSUnavailableError("Không có lời thoại để lồng tiếng")

    target_dur = sum(max(0.5, float(d)) for _, d in lines)
    prov = (provider_name or "edge").strip().lower()
    is_tone_sim = prov in ("test_tone", "local")
    script_text = ". ".join(t for t, _ in non_empty)

    if is_tone_sim:
        raw_track = synthesize_local_waveform(lines, work_dir=work_dir)
    elif prov == "edge":
        try:
            raw_track = synthesize_edge_python_or_cli(script_text, voice=voice, work_dir=work_dir)
        except TTSUnavailableError:
            if lang == "vi":
                vn_preset = "NamMinh" in voice and "Minh Quân" or "Trúc Ly"
                raw_track = synthesize_vieneu_single(
                    script_text, work_dir=work_dir, voice=vn_preset, paths=paths
                )
                prov = "vieneu"
            else:
                raise
    elif prov == "vieneu":
        raw_track = synthesize_vieneu_single(
            script_text,
            work_dir=work_dir,
            voice=voice,
            ref_audio=ref_audio,
            paths=paths,
        )
    else:
        raise TTSUnavailableError(f"Chưa hỗ trợ TTS provider '{provider_name}'")

    fitted_path, fitted_dur, fitted_timings, factor = fit_voice_to_budget(
        raw_track.audio_path,
        target_dur,
        raw_track.word_timings,
        max_atempo=max_atempo,
        out_path=work_dir / "voice_fitted.wav",
    )
    warnings: list[str] = []
    if is_tone_sim:
        warnings.append("Đang dùng âm hiệu nhịp kiểm thử (test_tone), không phải giọng người thật.")
    if factor > 1.02:
        warnings.append(
            f"Tự động tăng nhịp giọng x{factor:.2f} để khớp tổng thời lượng hình {target_dur:.1f}s"
        )
    if fitted_dur > target_dur + 0.35:
        warnings.append(
            f"Lời đọc dài {fitted_dur:.1f}s vượt hình {target_dur:.1f}s: phần cuối có thể bị cắt, nên rút gọn chữ ({lang})"
        )

    return (
        SynthesizedTrack(
            audio_path=fitted_path,
            duration_s=fitted_dur,
            word_timings=fitted_timings,
            applied_atempo=factor,
            provider=prov,
        ),
        warnings,
    )


def synthesize_with_local_fallback(
    paths: AppPaths,
    *,
    lines: list[tuple[str, float]],
    lang: str,
    voice: str,
    work_dir: Path,
    tts_provider: str | None = None,
    used_providers_out: list[str] | None = None,
) -> Path:
    """Synthesizes mono 48kHz PCM WAV via Edge TTS, VieNeu CPU, or consented Channel Voice with honest `test_tone` fallback."""
    from videocreator.pipeline.channel_voices import resolve_voice_id_to_tts_spec

    cfg = load_settings(paths.config_file)
    explicit = (tts_provider or "").strip().lower()
    base_prov = explicit or (cfg.voice.en_provider if lang == "en" else cfg.voice.vi_provider)

    work_dir.mkdir(parents=True, exist_ok=True)
    prov, resolved_voice, ref_audio = resolve_voice_id_to_tts_spec(
        paths,
        voice,
        lang=lang,
        default_provider=base_prov,
    )

    if prov in ("edge", "vieneu"):
        try:
            track, _ = synthesize_speech_segments(
                lines,
                lang=lang,
                voice=resolved_voice,
                provider_name=prov,
                work_dir=work_dir,
                max_atempo=1.15,
                ref_audio=ref_audio,
                paths=paths,
            )
            if used_providers_out is not None:
                used_providers_out.append(track.provider)
            return track.audio_path
        except TTSUnavailableError as exc:
            logger.warning(
                "Studio TTS (%s/%s) unavailable; falling back to test_tone: %s",
                prov,
                resolved_voice,
                exc,
            )

    tone_prov = explicit if explicit in ("test_tone", "local") else "test_tone"
    track, _ = synthesize_speech_segments(
        lines,
        lang=lang,
        voice=resolved_voice,
        provider_name=tone_prov,
        work_dir=work_dir,
        max_atempo=1.15,
    )
    if used_providers_out is not None:
        used_providers_out.append(tone_prov)
    return track.audio_path


def synthesize_timed_speaker_segments(
    paths: AppPaths,
    timed_items: list[dict[str, Any]],
    *,
    work_dir: Path,
    preview_out_dir: Path | None = None,
    max_atempo: float = 1.35,
) -> tuple[SynthesizedTrack, list[str], list[str]]:
    """Synthesizes per-segment multi-speaker audio aligned to exact timeline offsets `[offset_s, offset_s + dur_s]`."""
    import numpy as np
    import soundfile as sf

    work_dir.mkdir(parents=True, exist_ok=True)
    if preview_out_dir is not None:
        preview_out_dir.mkdir(parents=True, exist_ok=True)

    sr = 48000
    total_dur = max(
        0.8,
        max((float(it["offset_s"]) + float(it["duration_s"]) for it in timed_items), default=1.0),
    )
    master_samples = np.zeros(int(round(total_dur * sr)) + sr // 4, dtype=np.float32)
    all_timings: list[WordTiming] = []
    preview_files: list[str] = []
    warnings: list[str] = []
    used_providers: set[str] = set()

    needs_vieneu = any(str(it.get("provider") or "").lower() == "vieneu" for it in timed_items)
    vieneu_tts = None
    enrolled_cache: dict[str, dict[str, Any]] = {}
    if needs_vieneu:
        from vieneu.v3nano import V3NanoVieNeuTTS

        model_dir = resolve_vieneu_model_dir(paths)
        vieneu_tts = V3NanoVieNeuTTS(onnx_dir=str(model_dir))

    try:
        for idx, item in enumerate(timed_items):
            txt = str(item.get("text") or "").strip()
            off_s = max(0.0, float(item.get("offset_s") or 0.0))
            dur_s = max(0.45, float(item.get("duration_s") or 1.5))
            prov = str(item.get("provider") or "edge").strip().lower()
            voice = str(item.get("voice") or "vi-VN-HoaiMyNeural").strip()
            ref_audio: Path | None = item.get("ref_audio")
            stem = f"seg_{idx:03d}"

            if not txt:
                preview_files.append("")
                continue

            if prov in ("test_tone", "local"):
                seg_track = synthesize_local_waveform([(txt, dur_s)], work_dir=work_dir / stem)
                used_providers.add("test_tone")
            elif prov == "vieneu":
                enrolled = None
                if ref_audio is not None and ref_audio.is_file() and vieneu_tts is not None:
                    cache_key = str(ref_audio.resolve())
                    if cache_key not in enrolled_cache:
                        spk_emb, style_tok = vieneu_tts.encode_reference(
                            str(ref_audio), denoise=True
                        )
                        enrolled_cache[cache_key] = {"speaker_emb": spk_emb, "style": style_tok}
                    enrolled = enrolled_cache[cache_key]
                seg_track = synthesize_vieneu_single(
                    txt,
                    work_dir=work_dir / stem,
                    voice=voice,
                    ref_audio=ref_audio if enrolled is None else None,
                    paths=paths,
                    stem=stem,
                    tts_instance=vieneu_tts,
                    enrolled_voice=enrolled,
                )
                used_providers.add("vieneu")
            else:
                try:
                    seg_track = synthesize_edge_python_or_cli(
                        txt,
                        voice=voice,
                        work_dir=work_dir / stem,
                        stem=stem,
                    )
                    used_providers.add("edge")
                except TTSUnavailableError:
                    if voice.lower().startswith("vi-"):
                        if vieneu_tts is None:
                            from vieneu.v3nano import V3NanoVieNeuTTS

                            vieneu_tts = V3NanoVieNeuTTS(
                                onnx_dir=str(resolve_vieneu_model_dir(paths))
                            )
                        vn_voice = "Minh Quân" if "nam" in voice.lower() else "Trúc Ly"
                        seg_track = synthesize_vieneu_single(
                            txt,
                            work_dir=work_dir / stem,
                            voice=vn_voice,
                            paths=paths,
                            stem=stem,
                            tts_instance=vieneu_tts,
                        )
                        used_providers.add("vieneu")
                    else:
                        raise

            fitted_wav, _f_dur, f_timings, factor = fit_voice_to_budget(
                seg_track.audio_path,
                dur_s,
                seg_track.word_timings,
                max_atempo=max_atempo,
                out_path=work_dir / stem / f"{stem}_fitted.wav",
            )
            if factor > 1.28:
                warnings.append(f"Đoạn #{idx + 1}: tăng tốc giọng x{factor:.2f}")

            if preview_out_dir is not None:
                prev_dst = preview_out_dir / f"seg_{idx:03d}.wav"
                shutil.copy2(fitted_wav, prev_dst)
                preview_files.append(str(prev_dst))
            else:
                preview_files.append(str(fitted_wav))

            seg_pcm, seg_sr = sf.read(str(fitted_wav), dtype="float32", always_2d=False)
            if seg_pcm.ndim > 1:
                seg_pcm = seg_pcm.mean(axis=1)
            if seg_sr != sr:
                import soxr

                seg_pcm = soxr.resample(seg_pcm, seg_sr, sr).astype(np.float32)

            max_len = int(round((dur_s + 0.06) * sr))
            seg_pcm = seg_pcm[:max_len]
            start_sample = int(round(off_s * sr))
            end_sample = start_sample + seg_pcm.shape[0]
            if end_sample > master_samples.shape[0]:
                master_samples = np.pad(master_samples, (0, end_sample - master_samples.shape[0]))
            master_samples[start_sample:end_sample] += seg_pcm

            for wt in f_timings:
                w_st = round(off_s + wt.start_s, 3)
                w_en = round(min(off_s + dur_s, off_s + wt.end_s), 3)
                if w_en > w_st:
                    all_timings.append(WordTiming(word=wt.word, start_s=w_st, end_s=w_en))
    finally:
        if vieneu_tts is not None:
            vieneu_tts.close()
            del vieneu_tts
            gc.collect()

    master_wav = work_dir / "voice_master.wav"
    trimmed_samples = np.clip(master_samples[: int(round(total_dur * sr))], -1.0, 1.0)
    sf.write(str(master_wav), trimmed_samples, sr, subtype="PCM_16")
    actual_dur = probe_duration(master_wav)
    prov_summary = "+".join(sorted(used_providers)) if used_providers else "edge"
    return (
        SynthesizedTrack(
            audio_path=master_wav,
            duration_s=actual_dur,
            word_timings=all_timings,
            applied_atempo=1.0,
            provider=prov_summary,
        ),
        preview_files,
        warnings,
    )


__all__ = [
    "SynthesizedTrack",
    "TTSUnavailableError",
    "WordTiming",
    "fit_voice_to_budget",
    "synthesize_speech_segments",
    "synthesize_timed_speaker_segments",
    "synthesize_vieneu_single",
    "synthesize_with_local_fallback",
    "trim_voice_silence",
]
