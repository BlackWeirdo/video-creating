"""FastAPI application factory, lifespan management, dashboard, and settings routes."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.api.routes_ai import router as ai_router
from videocreator.api.routes_approval import router as approval_router
from videocreator.api.routes_assets import router as assets_router
from videocreator.api.routes_broll import router as broll_router
from videocreator.api.routes_footage import router as footage_router
from videocreator.api.routes_footage import run_analyse_footage
from videocreator.api.routes_manual import router as manual_router
from videocreator.api.routes_oauth import router as oauth_router
from videocreator.api.routes_posting import router as posting_router
from videocreator.api.routes_products import router as products_router
from videocreator.api.routes_studio import router as studio_router
from videocreator.api.routes_trends import router as trends_router
from videocreator.api.routes_trends import run_scan_and_suggest_job
from videocreator.api.routes_videos import router as videos_router
from videocreator.api.routes_videos import run_plan_footage
from videocreator.api.routes_voices import router as voices_router
from videocreator.auth import NonLocalhostBasicAuthMiddleware
from videocreator.config import Settings, load_settings, save_settings
from videocreator.db import get_conn, migrate, query_all, record_audit
from videocreator.jobs import JobRegistry, JobWorker, default_registry, recover_interrupted_jobs
from videocreator.logging_setup import setup_logging
from videocreator.paths import AppPaths, get_paths
from videocreator.pipeline.broll_suggest import BROLL_SUGGEST_JOB_KIND, run_broll_suggest_job
from videocreator.pipeline.describe import run_describe_footage
from videocreator.pipeline.planner import replan_video
from videocreator.pipeline.render import render_video
from videocreator.scheduler import AppScheduler
from videocreator.secrets_store import SecretsStore
from videocreator.studio.agent import run_studio_job
from videocreator.studio.session import STUDIO_JOB_KIND, recover_stuck_studio_sessions
from videocreator.engines.mpt_service import MPTServiceManager
from videocreator.telegram_bot import TelegramBotService
from videocreator.transfer import ExportPasswordError, export_config_bundle, import_config_bundle

logger = logging.getLogger("videocreator.app")

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

FOOTAGE_STATUSES: tuple[str, ...] = ("imported", "analysing", "analysed", "failed")
VIDEO_STATUSES: tuple[str, ...] = (
    "planned",
    "rendering",
    "rendered",
    "scoring",
    "pending_approval",
    "approved",
    "scheduled",
    "posted",
    "failed",
    "rejected",
    "superseded",
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


def _collect_dashboard_stats(db_file: Path, settings: Settings) -> dict[str, Any]:
    footage_counts = {s: 0 for s in FOOTAGE_STATUSES}
    for row in query_all(
        db_file, "SELECT status, COUNT(*) AS cnt FROM footage GROUP BY status"
    ):
        footage_counts[str(row["status"])] = int(row["cnt"])

    video_counts = {s: 0 for s in VIDEO_STATUSES}
    for row in query_all(
        db_file, "SELECT status, COUNT(*) AS cnt FROM videos GROUP BY status"
    ):
        video_counts[str(row["status"])] = int(row["cnt"])

    job_counts: dict[str, int] = {
        "queued": 0,
        "running": 0,
        "waiting_quota": 0,
        "done": 0,
        "failed": 0,
    }
    for row in query_all(
        db_file, "SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status"
    ):
        job_counts[str(row["status"])] = int(row["cnt"])

    recent_jobs = query_all(
        db_file,
        """
        SELECT id, kind, ref_id, status, error, created_at, started_at, finished_at
        FROM jobs
        ORDER BY id DESC
        LIMIT 10
        """,
    )

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage_rows = query_all(
        db_file,
        """
        SELECT route, kind, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0.0) AS cost_usd
        FROM ai_usage
        WHERE day = ?
        GROUP BY route, kind
        """,
        (today_utc,),
    )
    sub_calls = 0
    api_calls = 0
    text_api_cost = 0.0
    gen_api_cost = 0.0
    studio_api_cost = 0.0
    for r in usage_rows:
        route = str(r["route"])
        kind = str(r["kind"])
        calls = int(r["calls"])
        cost = float(r["cost_usd"])
        if route == "subscription":
            sub_calls += calls
        elif route == "api":
            api_calls += calls
            if kind == "videogen":
                gen_api_cost += cost
            elif kind == "studio":
                studio_api_cost += cost
            else:
                text_api_cost += cost

    provider_states = query_all(
        db_file, "SELECT name, resting_until, last_error FROM provider_state ORDER BY name"
    )

    return {
        "footage_counts": footage_counts,
        "video_counts": video_counts,
        "job_counts": job_counts,
        "recent_jobs": recent_jobs,
        "ai_today": {
            "day": today_utc,
            "subscription_calls": sub_calls,
            "api_calls": api_calls,
            "text_api_cost_usd": round(text_api_cost, 4),
            "generative_api_cost_usd": round(gen_api_cost, 4),
            "studio_api_cost_usd": round(studio_api_cost, 4),
            "daily_limit_usd": settings.budget.daily_usd,
            "generative_limit_usd": settings.budget.generative_daily_usd,
            "studio_limit_usd": settings.budget.studio_daily_usd,
        },
        "provider_states": provider_states,
    }


def create_app(
    data_dir: Path | str | None = None,
    *,
    start_worker: bool = True,
    job_registry: JobRegistry = default_registry,
) -> FastAPI:
    paths: AppPaths = get_paths(data_dir)
    migrate(paths.db_file)
    secrets = SecretsStore(paths.secrets_file)
    setup_logging(paths.log_file, secrets_store=secrets)
    initial_settings = load_settings(paths.config_file)

    job_registry.register(
        "analyse",
        lambda ref_id: run_analyse_footage(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "describe",
        lambda ref_id: run_describe_footage(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "plan",
        lambda ref_id: run_plan_footage(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "replan",
        lambda ref_id: replan_video(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "render",
        lambda ref_id: render_video(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "scan_trends",
        lambda ref_id: run_scan_and_suggest_job(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "trend_scan",
        lambda ref_id: run_scan_and_suggest_job(paths, int(ref_id or 0)),
    )
    job_registry.register(
        STUDIO_JOB_KIND,
        lambda ref_id: str(run_studio_job(paths, int(ref_id or 0)).get("status")),
    )
    job_registry.register(
        BROLL_SUGGEST_JOB_KIND,
        lambda _ref_id: run_broll_suggest_job(paths),
    )

    worker = JobWorker(paths.db_file, registry=job_registry)
    tg_service = TelegramBotService(paths, secrets)
    scheduler = AppScheduler(paths)
    mpt_service = MPTServiceManager(paths)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        recover_interrupted_jobs(paths.db_file)
        recover_stuck_studio_sessions(paths.db_file)
        current_settings = load_settings(paths.config_file)
        logger.info(
            "Starting Video Creator v%s (role=%s, data_dir=%s)",
            __version__,
            current_settings.role,
            paths.data_dir,
        )
        if current_settings.role == "server" and start_worker:
            worker.start()
            scheduler.start()
            await tg_service.start()
            mpt_service.start()
        try:
            yield
        finally:
            mpt_service.stop()
            scheduler.stop()
            await tg_service.stop()
            await worker.stop()
            logger.info("Stopped Video Creator")

    app = FastAPI(
        title="Video Creator",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.paths = paths
    app.state.secrets = secrets
    app.state.worker = worker
    app.add_middleware(
        NonLocalhostBasicAuthMiddleware,
        config_file=paths.config_file,
        secrets_store=secrets,
    )

    if paths.static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(paths.static_dir)), name="static")
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    app.include_router(products_router)
    app.include_router(footage_router)
    app.include_router(videos_router)
    app.include_router(ai_router)
    app.include_router(assets_router)
    app.include_router(approval_router)
    app.include_router(posting_router)
    app.include_router(oauth_router)
    app.include_router(trends_router)
    app.include_router(broll_router)
    app.include_router(manual_router)
    app.include_router(voices_router)
    app.include_router(studio_router)

    @app.get("/health")
    async def health() -> JSONResponse:
        cfg = load_settings(paths.config_file)
        return JSONResponse(
            {
                "status": "ok",
                "role": cfg.role,
                "version": __version__,
            }
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        cfg = load_settings(paths.config_file)
        stats = _collect_dashboard_stats(paths.db_file, cfg)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "page": "home",
                "settings": cfg,
                "stats": stats,
                "version": __version__,
            },
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request, saved: str | None = None) -> HTMLResponse:
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

    @app.post("/settings/config")
    async def update_config(
        role: str = Form("server"),
        host: str = Form("127.0.0.1"),
        port: int = Form(8765),
        daily_usd: float = Form(5.0),
        generative_daily_usd: float = Form(15.0),
        studio_daily_usd: float = Form(10.0),
        api_fallback: str = Form("ask"),
        offpeak_hours: str = Form("23:00-06:00"),
        vision_routes: str = Form("claude_cli, gemini_api"),
        writer_routes: str = Form("claude_cli, muse_api, claude_api"),
        checker_routes: str = Form("claude_cli, claude_api, gemini_api"),
        studio_routes: str = Form("claude_cli, claude_api"),
        timezone_name: str = Form("Asia/Ho_Chi_Minh"),
        schedule_auto: bool = Form(False),
        schedule_slots: str = Form("08:00, 11:30, 15:00, 19:00, 21:00"),
        allowed_chat_ids: str = Form(""),
        approver_user_ids: str = Form(""),
        quiet_hours: str = Form("22:00-07:00"),
        r2_bucket: str = Form(""),
        r2_public_base: str = Form(""),
    ) -> RedirectResponse:
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
        cfg.ai.routes.vision = _parse_str_list(vision_routes)
        cfg.ai.routes.writer = _parse_str_list(writer_routes)
        cfg.ai.routes.checker = _parse_str_list(checker_routes)
        cfg.ai.routes.studio = _parse_str_list(studio_routes)
        cfg.schedule.timezone = timezone_name.strip() or "Asia/Ho_Chi_Minh"
        cfg.schedule.auto = bool(schedule_auto)
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

    @app.post("/settings/secrets")
    async def update_secret(
        name: str = Form(...),
        value: str = Form(""),
        action: str = Form("set"),
    ) -> RedirectResponse:
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

    @app.post("/settings/export")
    async def export_settings_route(password: str = Form(...)) -> FileResponse:
        dest_vcx = paths.work_dir / "videocreator-export.vcx"
        try:
            export_config_bundle(paths, password, dest_vcx, secrets_store=secrets)
        except ExportPasswordError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return FileResponse(
            dest_vcx,
            media_type="application/octet-stream",
            filename="videocreator-export.vcx",
        )

    @app.post("/settings/import")
    async def import_settings_route(
        file: UploadFile = File(...),
        password: str = Form(...),
        as_server: bool = Form(False),
    ) -> RedirectResponse:
        tmp_vcx = paths.work_dir / "videocreator-import.vcx"
        try:
            with tmp_vcx.open("wb") as out_f:
                while chunk := await file.read(1024 * 1024):
                    out_f.write(chunk)
            import_config_bundle(
                paths,
                tmp_vcx,
                password,
                as_server=as_server,
                secrets_store=secrets,
            )
        except (ExportPasswordError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            tmp_vcx.unlink(missing_ok=True)
        return RedirectResponse(url="/settings?saved=imported", status_code=303)

    return app
