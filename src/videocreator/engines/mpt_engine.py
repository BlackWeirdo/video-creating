"""Voice-over via MoneyPrinterTurbo with automatic fallback to subtitles-only FFmpeg render (Phase 09)."""
from __future__ import annotations

import logging
from pathlib import Path

from videocreator.config import load_settings
from videocreator.db import get_conn, record_audit
from videocreator.engines.mpt_client import MPTClient, MPTClientError, VoiceTrack
from videocreator.paths import AppPaths

logger = logging.getLogger("videocreator.engines.mpt_engine")

# Voices verified end to end against MoneyPrinterTurbo v1.3.9 in spike S12 (Edge TTS, no API key).
DEFAULT_VOICES: dict[str, tuple[str, str]] = {
    "vi": ("vi-VN", "vi-VN-HoaiMyNeural-Female"),
    "en": ("en-US", "en-US-JennyNeural-Female"),
}

FALLBACK_NOTE = "Không lồng tiếng được (dịch vụ MoneyPrinterTurbo không phản hồi); video chỉ có phụ đề"


def resolve_voice_for_lang(paths: AppPaths, voice_lang: str) -> tuple[str, str]:
    """Returns `(language, voice_name)` for `voice_lang` (`vi` or `en`), preferring the configured voice."""
    settings = load_settings(paths.config_file)
    language, default_voice = DEFAULT_VOICES["en" if voice_lang == "en" else "vi"]
    configured = settings.voice.en_voice if voice_lang == "en" else settings.voice.vi_voice
    return language, (configured or default_voice)


def try_voice_with_mpt(
    paths: AppPaths,
    video_id: int,
    *,
    script_lines: list[str],
    voice_lang: str,
    work_dir: Path,
    mpt_client: MPTClient | None = None,
) -> VoiceTrack | None:
    """Asks MoneyPrinterTurbo for the voice-over and its SRT (`FR-REN-03`, `FR-REN-07`).

    Returns `None` when MPT is offline or fails; the fallback is noted on `videos.quality_notes`
    so the reviewer sees it (`FR-REN-05`) and the caller renders subtitles-only with FFmpeg.
    """
    script_text = " ".join(line.strip() for line in script_lines if line and line.strip())
    if not script_text:
        return None
    settings = load_settings(paths.config_file)
    language, voice_name = resolve_voice_for_lang(paths, voice_lang)
    client = mpt_client or MPTClient(base_url=f"http://127.0.0.1:{settings.mpt.port}")
    try:
        return client.synthesize_voice(
            script_text=script_text,
            voice_name=voice_name,
            language=language,
            dest_dir=work_dir,
        )
    except MPTClientError as exc:
        logger.warning("MPT voice unavailable for video #%d (%s); rendering subtitles only", video_id, exc)
        add_quality_note(paths, video_id, FALLBACK_NOTE)
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE videos SET engine = 'ffmpeg' WHERE id = ?", (video_id,))
            record_audit(
                conn,
                actor="worker",
                action="video.mpt_fallback_to_ffmpeg",
                object_type="video",
                object_id=video_id,
                detail=str(exc)[:200],
            )
        return None


def add_quality_note(paths: AppPaths, video_id: int, note: str) -> None:
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE videos
            SET quality_notes = CASE
                    WHEN quality_notes IS NULL OR quality_notes = '' THEN ?
                    ELSE quality_notes || ' | ' || ?
                END
            WHERE id = ?
            """,
            (note, note, video_id),
        )
