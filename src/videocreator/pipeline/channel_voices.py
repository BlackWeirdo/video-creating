"""Consented Workspace / Character Channel Voices (5-10s MC voice samples for VieNeu-TTS CPU) (Stage R4)."""
from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration
from videocreator.tts.synthesizer import trim_voice_silence
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.channel_voices")

VIENEU_PRESET_NAMES: frozenset[str] = frozenset(
    {
        "Minh Quân",
        "Trúc Ly",
        "Ái Hân",
        "Adam",
        "Mỹ Duyên",
        "Đức Trí",
        "Hữu Quân",
        "Xuân Tiên",
        "Mai Anh",
        "Anh Khôi",
        "Mạnh Dũng",
    }
)


def _hydrate_channel_voice(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["consent_confirmed"] = bool(int(row.get("consent_confirmed") or 0))
    rel = str(row.get("ref_audio_path") or "").lstrip("/")
    out["audio_url"] = f"/files/{rel}" if rel else ""
    out["voice_token"] = f"channel_voice:{row['id']}"
    return out


def list_channel_voices(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM channel_voices WHERE workspace_id = ? ORDER BY id DESC",
        (int(workspace_id),),
    )
    return [_hydrate_channel_voice(r) for r in rows]


def get_channel_voice(db_file: Path, voice_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM channel_voices WHERE id = ?", (int(voice_id),))
    return _hydrate_channel_voice(row) if row else None


def create_channel_voice(
    paths: AppPaths,
    *,
    workspace_id: int,
    name: str,
    speaker_name: str,
    consent_confirmed: bool,
    raw_audio_bytes: bytes,
    filename: str = "sample.wav",
    character_id: int | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    """Validates consent, normalizes 5-10s MC audio sample to 24kHz mono WAV, and stores a Channel Voice."""
    require_workspace(paths.db_file, workspace_id)
    if not consent_confirmed:
        raise PermissionError(
            "Lưu Giọng kênh yêu cầu xác nhận sự đồng ý của chủ giọng nói (`consent_confirmed=true`)."
        )
    clean_name = (name or "").strip()
    clean_speaker = (speaker_name or "").strip()
    if not clean_name or not clean_speaker:
        raise ValueError("Cần nhập tên Giọng kênh và họ tên MC / chủ giọng")
    if len(raw_audio_bytes) < 256:
        raise ValueError("File mẫu giọng trống hoặc quá ngắn")

    suffix = Path(filename or "sample.wav").suffix.lower() or ".wav"
    if suffix not in (".wav", ".mp3", ".webm", ".ogg", ".m4a", ".mp4"):
        raise ValueError("Chỉ hỗ trợ file âm thanh (.wav/.mp3/.webm/.ogg/.m4a)")

    cv_dir = paths.media_dir / "channel_voices"
    cv_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(6)
    raw_tmp = cv_dir / f"_raw_{token}{suffix}"
    trimmed_48k = cv_dir / f"_trim_{token}.wav"
    final_wav = cv_dir / f"ws_{int(workspace_id)}_cv_{token}.wav"

    raw_tmp.write_bytes(raw_audio_bytes)
    try:
        trim_voice_silence(raw_tmp, trimmed_48k)
        run_ffmpeg(
            [
                "-i",
                str(trimmed_48k.resolve()),
                "-c:a",
                "pcm_s16le",
                "-ar",
                "24000",
                "-ac",
                "1",
                "-t",
                "25.0",
                str(final_wav.resolve()),
            ]
        )
        dur_s = round(probe_duration(final_wav), 2)
    finally:
        raw_tmp.unlink(missing_ok=True)
        trimmed_48k.unlink(missing_ok=True)

    if dur_s < 1.8:
        final_wav.unlink(missing_ok=True)
        raise ValueError(
            f"Mẫu giọng sau khi cắt khoảng lặng chỉ dài {dur_s:.1f}s (cần tối thiểu ~3–10 giây giọng nói rõ)."
        )

    rel_audio = f"channel_voices/{final_wav.name}"
    char_id_val = int(character_id) if character_id and int(character_id) > 0 else None

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO channel_voices (
                workspace_id, character_id, name, speaker_name,
                consent_confirmed, ref_audio_path, duration_s
            )
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (int(workspace_id), char_id_val, clean_name, clean_speaker, rel_audio, dur_s),
        )
        cv_id = int(cur.lastrowid)
        if char_id_val is not None:
            conn.execute(
                "UPDATE characters SET voice_id = ? WHERE id = ? AND workspace_id = ?",
                (f"channel_voice:{cv_id}", char_id_val, int(workspace_id)),
            )
        record_audit(
            conn,
            actor=actor,
            action="create_channel_voice",
            object_type="channel_voice",
            object_id=cv_id,
            detail=f"ws={workspace_id} speaker='{clean_speaker}' dur={dur_s}s char={char_id_val}",
        )

    created = get_channel_voice(paths.db_file, cv_id)
    assert created is not None
    return created


def delete_channel_voice(paths: AppPaths, voice_id: int, *, actor: str = "api") -> bool:
    cv = get_channel_voice(paths.db_file, voice_id)
    if cv is None:
        return False
    ref_abs = paths.media_dir / str(cv["ref_audio_path"])
    ref_abs.unlink(missing_ok=True)
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM channel_voices WHERE id = ?", (int(voice_id),))
        conn.execute(
            "UPDATE characters SET voice_id = 'vi-VN-HoaiMyNeural' WHERE voice_id = ?",
            (f"channel_voice:{voice_id}",),
        )
        record_audit(
            conn,
            actor=actor,
            action="delete_channel_voice",
            object_type="channel_voice",
            object_id=int(voice_id),
            detail=str(cv["name"]),
        )
    return True


def resolve_voice_id_to_tts_spec(
    paths: AppPaths,
    raw_voice_id: str | None,
    *,
    lang: str = "vi",
    default_provider: str = "edge",
) -> tuple[str, str, Path | None]:
    """Resolves a voice identifier (`edge`, `vieneu:<name>`, or `channel_voice:<id>`) to `(provider, voice, ref_audio)`."""
    clean = (raw_voice_id or "").strip()
    def_prov = (default_provider or "edge").strip().lower()
    if def_prov in ("test_tone", "local"):
        return def_prov, (clean or "vi-VN-HoaiMyNeural"), None

    # 1. Consented Channel Voice (`channel_voice:<id>`)
    if clean.startswith("channel_voice:"):
        try:
            cv_id = int(clean.split(":", 1)[1].strip())
        except ValueError:
            cv_id = 0
        cv = get_channel_voice(paths.db_file, cv_id) if cv_id > 0 else None
        if cv and cv.get("consent_confirmed"):
            ref_abs = paths.media_dir / str(cv["ref_audio_path"])
            vieneu_m = get_local_model(paths, "vieneu_tts_vi")
            if ref_abs.is_file() and vieneu_m and vieneu_m.get("status") == "ready" and vieneu_m.get("installed_on_disk"):
                return "vieneu", "Minh Quân", ref_abs
        clean = "vi-VN-HoaiMyNeural"

    # 2. Explicit VieNeu CPU preset (`vieneu:Trúc Ly` or bare preset name)
    if clean.startswith("vieneu:"):
        preset = clean.split(":", 1)[1].strip() or "Minh Quân"
        vieneu_m = get_local_model(paths, "vieneu_tts_vi")
        if vieneu_m and vieneu_m.get("status") == "ready" and vieneu_m.get("installed_on_disk"):
            return "vieneu", preset, None
        return "edge", "vi-VN-HoaiMyNeural", None

    if clean in VIENEU_PRESET_NAMES or def_prov == "vieneu":
        vieneu_m = get_local_model(paths, "vieneu_tts_vi")
        if vieneu_m and vieneu_m.get("status") == "ready" and vieneu_m.get("installed_on_disk"):
            preset = clean if clean in VIENEU_PRESET_NAMES else "Minh Quân"
            return "vieneu", preset, None

    # 3. Default Edge TTS neural voice
    if not clean:
        clean = "en-US-JennyNeural" if lang == "en" else "vi-VN-HoaiMyNeural"
    return "edge", clean, None
