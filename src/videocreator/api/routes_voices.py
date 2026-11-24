"""Voice provider selection, default Vietnamese/English voices, and batch render routes (Phase 09, FR-REN-06, FR-REN-09)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, record_audit
from videocreator.engines.mpt_service import MPTServiceManager
from videocreator.paths import AppPaths
from videocreator.pipeline.render_batch import enqueue_batch_render
from videocreator.templating import get_templates

router = APIRouter()

AVAILABLE_VOICE_CATALOG: list[dict[str, str]] = [
    {"provider": "edge", "lang": "vi", "voice": "vi-VN-HoaiMyNeural-Female", "label": "Edge TTS: Hoài My (nữ, tiếng Việt)"},
    {"provider": "edge", "lang": "vi", "voice": "vi-VN-NamMinhNeural-Male", "label": "Edge TTS: Nam Minh (nam, tiếng Việt)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Minh Quân", "label": "VieNeu CPU: Minh Quân (nam Bắc, tự nhiên)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Trúc Ly", "label": "VieNeu CPU: Trúc Ly (nữ Bắc, tự nhiên)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Ái Hân", "label": "VieNeu CPU: Ái Hân (nữ miền Nam, tin tức)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Adam", "label": "VieNeu CPU: Adam (nam miền Nam, tự nhiên)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Mỹ Duyên", "label": "VieNeu CPU: Mỹ Duyên (nữ Bắc, kể chuyện)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Đức Trí", "label": "VieNeu CPU: Đức Trí (nam Bắc, đọc truyện)"},
    {"provider": "edge", "lang": "en", "voice": "en-US-JennyNeural-Female", "label": "Edge TTS: Jenny (female, English)"},
    {"provider": "edge", "lang": "en", "voice": "en-US-GuyNeural-Male", "label": "Edge TTS: Guy (male, English)"},
]

@router.get("/voices", response_class=HTMLResponse)
async def voices_page(
    request: Request,
    saved: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)
    mpt_mgr = MPTServiceManager(paths)

    return templates.TemplateResponse(
        request,
        "voices.html",
        {
            "page": "settings",
            "settings": cfg,
            "catalog": AVAILABLE_VOICE_CATALOG,
            "mpt_healthy": mpt_mgr.is_healthy(timeout_s=0.5),
            "saved": saved,
            "version": __version__,
        },
    )


@router.post("/voices/save")
async def save_voices_route(
    request: Request,
    vi_provider: str = Form("edge"),
    vi_voice: str = Form("vi-VN-HoaiMyNeural-Female"),
    en_provider: str = Form("edge"),
    en_voice: str = Form("en-US-JennyNeural-Female"),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    cfg.voice.vi_provider = vi_provider.strip() or "edge"
    cfg.voice.vi_voice = vi_voice.strip()
    cfg.voice.en_provider = en_provider.strip() or "edge"
    cfg.voice.en_voice = en_voice.strip()
    save_settings(paths.config_file, cfg)

    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="ui",
            action="voice.updated",
            object_type="config",
            detail=f"vi={cfg.voice.vi_provider}:{cfg.voice.vi_voice}, en={cfg.voice.en_provider}:{cfg.voice.en_voice}",
        )
    return RedirectResponse(url="/voices?saved=1", status_code=303)


@router.post("/videos/render-all-planned")
async def render_all_planned_route(request: Request) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    job_ids = enqueue_batch_render(paths.db_file)
    return RedirectResponse(url=f"/videos?msg=batch_queued_{len(job_ids)}", status_code=303)
