"""Default Voices configuration & TTS Preview endpoints for `/api/v1`."""
from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.config import load_settings, save_settings
from videocreator.paths import AppPaths
from videocreator.services.voices_catalog import AVAILABLE_VOICE_CATALOG
from videocreator.tts import TTSUnavailableError, count_syllables, synthesize_speech_segments

router = APIRouter()


class VoicesUpdateBody(BaseModel):
    vi_provider: str | None = None
    vi_voice: str | None = None
    en_provider: str | None = None
    en_voice: str | None = None


class VoicePreviewBody(BaseModel):
    text: str
    lang: Literal["vi", "en"] = "vi"
    provider: str | None = None
    voice: str | None = None
    target_duration_s: float = Field(default=4.0, ge=0.5, le=60.0)


@router.get("/voices")
async def api_v1_get_voices(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    return JSONResponse(
        {
            "catalog": AVAILABLE_VOICE_CATALOG,
            "voice": cfg.voice.model_dump(mode="json"),
        }
    )


@router.put("/voices")
async def api_v1_update_voices(request: Request, body: VoicesUpdateBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    if body.vi_provider is not None:
        cfg.voice.vi_provider = body.vi_provider.strip() or "edge"
    if body.vi_voice is not None:
        cfg.voice.vi_voice = body.vi_voice.strip()
    if body.en_provider is not None:
        cfg.voice.en_provider = body.en_provider.strip() or "edge"
    if body.en_voice is not None:
        cfg.voice.en_voice = body.en_voice.strip()
    save_settings(paths.config_file, cfg)
    return JSONResponse({"voice": cfg.voice.model_dump(mode="json")})


@router.post("/voices/preview")
async def api_v1_preview_voice(request: Request, body: VoicePreviewBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    clean_text = body.text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Text is required for TTS preview")
    cfg = load_settings(paths.config_file)
    prov = body.provider or (
        cfg.voice.en_provider if body.lang == "en" else cfg.voice.vi_provider
    )
    voice = body.voice or (cfg.voice.en_voice if body.lang == "en" else cfg.voice.vi_voice)

    tmp_work = paths.work_dir / f"preview_tts_{uuid.uuid4().hex}"
    previews_dir = paths.media_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    try:
        track, warnings = await asyncio.to_thread(
            synthesize_speech_segments,
            [(clean_text, body.target_duration_s)],
            lang=body.lang,
            voice=voice,
            provider_name=prov,
            work_dir=tmp_work,
        )
        out_name = f"tts_{uuid.uuid4().hex[:12]}.wav"
        dest_wav = previews_dir / out_name
        shutil.copy2(track.audio_path, dest_wav)
    except TTSUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(tmp_work, ignore_errors=True)

    return JSONResponse(
        {
            "audio_url": f"/files/previews/{out_name}",
            "provider": track.provider,
            "duration_s": round(track.duration_s, 3),
            "applied_atempo": track.applied_atempo,
            "syllables": count_syllables(clean_text, body.lang),
            "word_timings": [asdict(w) for w in track.word_timings],
            "warnings": warnings,
        }
    )
