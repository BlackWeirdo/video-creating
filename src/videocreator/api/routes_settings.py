"""Settings page: config.toml, secrets store, and export/import of the configuration bundle."""
from __future__ import annotations

import logging
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.templating import get_templates

logger = logging.getLogger("videocreator.app")

router = APIRouter()

KNOWN_SECRET_KEYS: tuple[tuple[str, str], ...] = (
    ("GEMINI_API_KEY", "Gemini API Key (dự phòng vision/writer/TTS)"),
    ("ANTHROPIC_API_KEY", "Anthropic API Key (dự phòng writer/checker/Studio)"),
    ("MUSE_API_KEY", "Meta Model API Key (Muse Spark)"),
    ("OPENAI_API_KEY", "OpenAI API Key (TTS dự phòng)"),
    ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token"),
    ("R2_ACCOUNT_ID", "Cloudflare R2 Account ID"),
    ("R2_ACCESS_KEY_ID", "Cloudflare R2 Access Key ID"),
    ("R2_SECRET_ACCESS_KEY", "Cloudflare R2 Secret Access Key"),
    ("YOUTUBE_API_KEY", "YouTube Data API v3 Key"),
    ("META_AD_LIBRARY_TOKEN", "Meta Ad Library Access Token"),
    ("THREADS_APP_ID", "Threads App ID (OAuth)"),
    ("THREADS_APP_SECRET", "Threads App Secret (OAuth)"),
    ("TIKTOK_CLIENT_KEY", "TikTok Client Key (OAuth)"),
    ("TIKTOK_CLIENT_SECRET", "TikTok Client Secret (OAuth)"),
    ("UI_PASSWORD", "Mật khẩu giao diện (khi mở ngoài 127.0.0.1)"),
)


def _parse_int_list(raw: str) -> list[int]:
    result: list[int] = []
    for part in raw.replace("\n", ",").split(","):
        cleaned = part.strip()
        if cleaned:
            result.append(int(cleaned))
    return result


def _parse_str_list(raw: str) -> list[str]:
    return [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: str | None = None) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    templates = get_templates(paths)
    cfg = load_settings(paths.config_file)
    stored_keys = set(secrets.list_keys())
    secret_items: list[dict[str, Any]] = []
    known_names = {k for k, _ in KNOWN_SECRET_KEYS}
    for key_name, label in KNOWN_SECRET_KEYS:
        secret_items.append(
            {
                "name": key_name,
                "label": label,
                "is_set": secrets.has(key_name),
            }
        )
    for extra_key in sorted(stored_keys - known_names):
        secret_items.append(
            {
                "name": extra_key,
                "label": "Khoá tuỳ chỉnh",
                "is_set": secrets.has(extra_key),
            }
        )
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "page": "settings",
            "settings": cfg,
            "secret_items": secret_items,
            "saved": saved,
            "data_dir": str(paths.data_dir),
            "version": __version__,
        },
    )


@router.post("/settings/config")
async def update_config(
    request: Request,
    role: str = Form("server"),
    host: str = Form("127.0.0.1"),
    port: int = Form(8765),
    daily_usd: float = Form(5.0),
    generative_daily_usd: float = Form(15.0),
    studio_daily_usd: float = Form(10.0),
    api_fallback: str = Form("ask"),
    offpeak_hours: str = Form("23:00-06:00"),
    claude_base_url: str = Form("https://api.shopdonk.com/v1"),
    vision_routes: str = Form("claude_api"),
    writer_routes: str = Form("claude_api"),
    checker_routes: str = Form("claude_cli, claude_api, gemini_api"),
    studio_routes: str = Form("claude_cli, claude_api"),
    timezone_name: str = Form("Asia/Ho_Chi_Minh"),
    schedule_auto: bool = Form(False),
    keep_original_audio: bool = Form(False),
    schedule_slots: str = Form("08:00, 11:30, 15:00, 19:00, 21:00"),
    allowed_chat_ids: str = Form(""),
    approver_user_ids: str = Form(""),
    quiet_hours: str = Form("22:00-07:00"),
    r2_bucket: str = Form(""),
    r2_public_base: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        ZoneInfo(timezone_name.strip() or "Asia/Ho_Chi_Minh")
    except (ZoneInfoNotFoundError, ValueError):
        return RedirectResponse(url="/settings?saved=bad_timezone", status_code=303)
    cfg = load_settings(paths.config_file)
    cfg.role = "client" if role == "client" else "server"
    cfg.host = host.strip() or "127.0.0.1"
    cfg.port = int(port)
    cfg.budget.daily_usd = float(daily_usd)
    cfg.budget.generative_daily_usd = float(generative_daily_usd)
    cfg.budget.studio_daily_usd = float(studio_daily_usd)
    if api_fallback in ("auto", "ask", "never"):
        cfg.ai.policy.api_fallback = api_fallback  # type: ignore[assignment]
    cfg.ai.policy.offpeak_hours = offpeak_hours.strip() or "23:00-06:00"
    cfg.ai.claude_base_url = claude_base_url.strip().rstrip("/")
    cfg.ai.routes.vision = _parse_str_list(vision_routes)
    cfg.ai.routes.writer = _parse_str_list(writer_routes)
    cfg.ai.routes.checker = _parse_str_list(checker_routes)
    cfg.ai.routes.studio = _parse_str_list(studio_routes)
    cfg.schedule.timezone = timezone_name.strip() or "Asia/Ho_Chi_Minh"
    cfg.schedule.auto = bool(schedule_auto)
    cfg.render.keep_original_audio = bool(keep_original_audio)
    cfg.schedule.slots = _parse_str_list(schedule_slots)
    cfg.telegram.allowed_chat_ids = _parse_int_list(allowed_chat_ids)
    cfg.telegram.approver_user_ids = _parse_int_list(approver_user_ids)
    cfg.telegram.quiet_hours = quiet_hours.strip() or "22:00-07:00"
    cfg.r2.bucket = r2_bucket.strip()
    cfg.r2.public_base = r2_public_base.strip()

    save_settings(paths.config_file, cfg)
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="ui",
            action="settings.update_config",
            object_type="config",
            detail=f"role={cfg.role}, daily_usd={cfg.budget.daily_usd}",
        )
    logger.info("Updated config.toml from Settings UI")
    return RedirectResponse(url="/settings?saved=config", status_code=303)


@router.post("/settings/secrets")
async def update_secret(
    request: Request,
    name: str = Form(...),
    value: str = Form(""),
    action: str = Form("set"),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    clean_name = name.strip()
    if not clean_name:
        return RedirectResponse(url="/settings?saved=error", status_code=303)

    if action == "delete":
        secrets.delete(clean_name)
        audit_action = "secrets.delete"
    else:
        if value:
            secrets.set(clean_name, value)
        audit_action = "secrets.set"

    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="ui",
            action=audit_action,
            object_type="secret",
            detail=clean_name,
        )
    logger.info("Updated secret key '%s' (action=%s)", clean_name, action)
    return RedirectResponse(url="/settings?saved=secret", status_code=303)
