"""Muse Gateway TTS engine (`/v1/audio/speech` + `/v1/tasks` for long text up to 6,000 chars per chunk)."""
from __future__ import annotations

import re
import time
from pathlib import Path

from videocreator.ai.budget import record_usage
from videocreator.config import load_settings
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import MuseGatewayError
from videocreator.paths import AppPaths, get_paths
from videocreator.pipeline.assembly import concat_wavs_padded
from videocreator.pipeline.probe import probe_duration
from videocreator.secrets_store import SecretsStore
from videocreator.tts.audio_fit import proportional_word_timings, trim_voice_silence
from videocreator.tts.types import SynthesizedTrack, TTSUnavailableError

MUSE_VOICE_NAMES: frozenset[str] = frozenset(
    {
        "Glad Kite",
        "Breathless Rosette",
        "Sparkling Whistle",
        "Kindhearted Jetty",
        "Questioning Satchel",
        "Tenacious Mooring",
        "Zealous Harbor",
        "Aria",
        "Dynamic Sparkler",
        "Mellow Saxophone",
        "Soothing Ribbon",
        "Helio",
        "Warm Pebble",
        "Bold Flag",
        "Boomy Mountain",
    }
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\r?\n+")
MAX_DIRECT_SPEECH_CHARS = 4000
MAX_TASK_SPEECH_CHARS = 5500


def _split_long_speech_text(text: str, max_chars: int = MAX_TASK_SPEECH_CHARS) -> list[str]:
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return [clean] if clean else []
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(clean) if s.strip()]
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if len(s) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(s), max_chars):
                chunks.append(s[i : i + max_chars])
            continue
        cand = f"{cur} {s}".strip() if cur else s
        if len(cand) > max_chars and cur:
            chunks.append(cur)
            cur = s
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks


def _synthesize_chunk_mp3(
    client: MuseGatewayClient,
    chunk: str,
    *,
    voice: str,
    lang: str,
    speed: float,
    dest_mp3: Path,
    poll_interval_s: float = 5.0,
) -> Path:
    dest_mp3.parent.mkdir(parents=True, exist_ok=True)
    if len(chunk) <= MAX_DIRECT_SPEECH_CHARS:
        mp3_bytes = client.synthesize_speech(
            text=chunk,
            model="muse-voice",
            voice=voice,
            language=lang,
            speed=speed,
        )
        dest_mp3.write_bytes(mp3_bytes)
        return dest_mp3

    created = client.create_task(
        {
            "model": "muse-voice",
            "prompt": chunk,
            "voice": voice,
            "language": lang,
            "speed": speed,
            "idempotency_key": f"vc-tts-{int(time.time() * 1000)}",
        }
    )
    gw_id = str(created["id"])
    deadline = time.monotonic() + 360.0
    while time.monotonic() < deadline:
        time.sleep(max(2.0, poll_interval_s))
        cur = client.get_task(gw_id)
        st = str(cur.get("status") or "running")
        if st in ("queued", "running"):
            continue
        if st != "succeeded":
            raise MuseGatewayError(f"Muse voice task failed: {cur.get('error')}")
        url = str(cur.get("url") or "")
        if not url:
            media = [m for m in (cur.get("media") or []) if isinstance(m, dict) and m.get("url")]
            url = str(media[-1]["url"]) if media else ""
        if not url:
            raise MuseGatewayError("Muse voice task returned empty media URL")
        client.download_media_to_file(url, dest_mp3)
        return dest_mp3

    raise MuseGatewayError("Muse voice task timed out")


def synthesize_muse_single(
    text: str,
    *,
    work_dir: Path,
    voice: str = "Glad Kite",
    lang: str = "vi",
    speed: float = 1.0,
    paths: AppPaths | None = None,
    stem: str = "muse_voice",
) -> SynthesizedTrack:
    """Synthesizes speech via Muse Gateway into 48kHz mono PCM WAV trimmed at -45 dBFS."""
    app_paths = paths or get_paths()
    settings = load_settings(app_paths.config_file)
    cfg = settings.muse_gateway
    if not cfg.enabled:
        raise TTSUnavailableError("Muse Gateway chưa được bật trong cấu hình")

    clean_voice = voice.split(":", 1)[1].strip() if voice.startswith("muse:") else voice.strip()
    if not clean_voice or clean_voice.lower().startswith(("vi-", "en-")):
        clean_voice = cfg.default_voice or ("Glad Kite" if lang.startswith("vi") else "Aria")

    chunks = _split_long_speech_text(text)
    if not chunks:
        raise TTSUnavailableError("Nội dung lồng tiếng Muse rỗng")

    work_dir.mkdir(parents=True, exist_ok=True)
    secrets = SecretsStore(app_paths.secrets_file)
    try:
        client = MuseGatewayClient(cfg, secrets)
        client.verify_ready_and_safe()

        wav_parts: list[Path] = []
        for idx, ch_txt in enumerate(chunks):
            mp3_file = work_dir / f"{stem}_part_{idx}.mp3"
            wav_file = work_dir / f"{stem}_part_{idx}.wav"
            _synthesize_chunk_mp3(
                client,
                ch_txt,
                voice=clean_voice,
                lang="vi" if lang.startswith("vi") else "en",
                speed=max(0.25, min(4.0, float(speed))),
                dest_mp3=mp3_file,
                poll_interval_s=float(cfg.poll_interval_s),
            )
            trim_voice_silence(mp3_file, wav_file)
            mp3_file.unlink(missing_ok=True)
            wav_parts.append(wav_file)
    except MuseGatewayError as exc:
        raise TTSUnavailableError(f"Muse Voice lỗi: {exc}") from exc

    final_wav = work_dir / f"{stem}.wav"
    if len(wav_parts) == 1:
        if wav_parts[0] != final_wav:
            wav_parts[0].replace(final_wav)
    else:
        concat_wavs_padded(wav_parts, final_wav, pad_between_s=0.18)

    dur_s = probe_duration(final_wav)
    timings = proportional_word_timings(text, dur_s)
    record_usage(
        app_paths.db_file,
        provider="muse_gateway",
        model="muse-voice",
        kind="tts",
        route="subscription",
        units_in=len(text),
        units_out=max(1, int(round(dur_s))),
        cost_usd=0.0,
    )
    return SynthesizedTrack(
        audio_path=final_wav,
        duration_s=dur_s,
        word_timings=timings,
        applied_atempo=1.0,
        provider="muse",
    )


__all__ = ["MUSE_VOICE_NAMES", "synthesize_muse_single"]
