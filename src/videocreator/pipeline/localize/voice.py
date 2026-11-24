"""Speaker voice resolution, Decision 7c cloning guards, and inline segment audio preview."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths
from videocreator.pipeline.localize.project import get_localize_project, validate_localize_policy
from videocreator.pipeline.probe import probe_duration
from videocreator.tts.synthesizer import synthesize_timed_speaker_segments


def resolve_segment_voice_spec(
    paths: AppPaths,
    proj: dict[str, Any],
    seg: dict[str, Any],
    *,
    requested_provider: str,
) -> tuple[str, str, Path | None]:
    """Resolve `(provider, voice_id, ref_audio_path)` for a segment based on speaker map & clone policy."""
    req = (requested_provider or "auto").strip().lower()
    if req in ("test_tone", "local"):
        return "test_tone", str(proj.get("voice_id") or "vi-VN-HoaiMyNeural"), None

    spk_id = str(seg.get("speaker_id") or "SPK_1")
    speakers_map = dict((proj.get("speaker_config") or {}).get("speakers") or {})
    spk_entry = dict(speakers_map.get(spk_id) or {})

    target_lang = str(proj.get("target_lang") or "vi").strip().lower()
    clone_enabled = bool(proj.get("clone_source_voice")) and bool(
        proj.get("clone_consent_confirmed")
    )

    if clone_enabled and target_lang.startswith("vi"):
        ref_rel = str(spk_entry.get("ref_audio_rel") or "").strip()
        if ref_rel:
            ref_abs = paths.media_dir / ref_rel
            proj_spk_root = (
                paths.media_dir / "localize" / f"proj_{proj['id']}" / "speakers"
            ).resolve()
            if ref_abs.is_file() and proj_spk_root in ref_abs.resolve().parents:
                vieneu_m = get_local_model(paths, "vieneu_tts_vi")
                if (
                    vieneu_m
                    and vieneu_m.get("status") == "ready"
                    and vieneu_m.get("installed_on_disk")
                ):
                    return "vieneu", "Minh Quân", ref_abs

    if req in ("edge", "vieneu"):
        prov = req
    else:
        prov = str(spk_entry.get("provider") or "edge").strip().lower()

    voice_id = str(
        seg.get("voice_id") or spk_entry.get("voice_id") or proj.get("voice_id") or ""
    ).strip()
    if prov == "vieneu":
        vieneu_m = get_local_model(paths, "vieneu_tts_vi")
        if not (
            vieneu_m
            and vieneu_m.get("status") == "ready"
            and vieneu_m.get("installed_on_disk")
        ):
            prov = "edge"
            voice_id = "vi-VN-HoaiMyNeural"
        elif not voice_id or voice_id.startswith(("vi-VN-", "en-US-")):
            voice_id = "Minh Quân"
    else:
        prov = "edge"
        if not voice_id or not ("-" in voice_id and "Neural" in voice_id):
            voice_id = (
                "en-US-JennyNeural" if target_lang.startswith("en") else "vi-VN-HoaiMyNeural"
            )

    return prov, voice_id, None


def preview_localize_segment_audio(
    paths: AppPaths,
    project_id: int,
    segment_index: int,
    *,
    tts_provider: str = "auto",
) -> dict[str, Any]:
    """Synthesize a single segment preview WAV for `/localize` inline playback."""
    proj = get_localize_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"Localize project #{project_id} not found")
    validate_localize_policy(
        paths.db_file,
        int(proj["workspace_id"]),
        str(proj["mode"]),
        clone_source_voice=bool(proj.get("clone_source_voice")),
        clone_consent_confirmed=bool(proj.get("clone_consent_confirmed")),
    )
    segments = list(proj.get("segments") or [])
    if segment_index < 0 or segment_index >= len(segments):
        raise ValueError(f"Segment index {segment_index} out of range")

    seg = segments[segment_index]
    txt = str(seg.get("translated_text") or seg.get("source_text") or "").strip()
    if not txt:
        raise ValueError("Đoạn thoại trống, không thể nghe thử")

    dur_s = max(0.6, float(seg.get("end_s", 2.0)) - float(seg.get("start_s", 0.0)))
    prov, voice_id, ref_audio = resolve_segment_voice_spec(
        paths, proj, seg, requested_provider=tts_provider
    )
    preview_dir = paths.media_dir / "localize" / f"proj_{project_id}" / "previews"
    work_dir = paths.work_dir / f"loc_preview_{project_id}_{segment_index}"
    try:
        track, prev_paths, _warns = synthesize_timed_speaker_segments(
            paths,
            [
                {
                    "text": txt,
                    "offset_s": 0.0,
                    "duration_s": dur_s,
                    "provider": prov,
                    "voice": voice_id,
                    "ref_audio": ref_audio,
                }
            ],
            work_dir=work_dir,
            preview_out_dir=preview_dir,
        )
        out_wav = Path(prev_paths[0]) if prev_paths and prev_paths[0] else track.audio_path
        dst_wav = preview_dir / f"seg_{segment_index:03d}.wav"
        if out_wav.resolve() != dst_wav.resolve():
            shutil.copy2(out_wav, dst_wav)
        rel = str(dst_wav.relative_to(paths.media_dir)).replace("\\", "/")
        return {
            "segment_index": segment_index,
            "audio_url": f"/files/{rel}",
            "duration_s": round(probe_duration(dst_wav), 3),
            "provider": track.provider,
            "voice_id": voice_id,
            "cloned": ref_audio is not None,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
