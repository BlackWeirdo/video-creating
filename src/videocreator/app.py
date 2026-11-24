"""FastAPI application factory and lifespan management."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from videocreator import __version__
from videocreator.api.routes_accounts import router as accounts_router
from videocreator.api.routes_ai import router as ai_router
from videocreator.api.routes_approval import router as approval_router
from videocreator.api.routes_assets import router as assets_router
from videocreator.api.routes_broll import router as broll_router
from videocreator.api.routes_config_bundle import router as config_bundle_router
from videocreator.api.routes_dashboard import router as dashboard_router
from videocreator.api.routes_footage import router as footage_router
from videocreator.api.routes_manual import router as manual_router
from videocreator.api.routes_media import router as media_router
from videocreator.api.routes_oauth import router as oauth_router
from videocreator.api.routes_performance import router as performance_router
from videocreator.api.routes_planning import router as planning_router
from videocreator.api.routes_posting import router as posting_router
from videocreator.api.routes_products import router as products_router
from videocreator.api.routes_settings import router as settings_router
from videocreator.api.routes_shots import router as shots_router
from videocreator.api.routes_studio import router as studio_router
from videocreator.api.routes_suggestions import router as suggestions_router
from videocreator.api.routes_trends import router as trends_router
from videocreator.api.routes_videos import router as videos_router
from videocreator.api.routes_voices import router as voices_router
from videocreator.api.routes_watchlist import router as watchlist_router
from videocreator.api.v1 import v1_router
from videocreator.auth import NonLocalhostBasicAuthMiddleware
from videocreator.config import load_settings
from videocreator.db import migrate
from videocreator.job_handlers import register_job_handlers
from videocreator.job_store import recover_interrupted_jobs
from videocreator.jobs import JobRegistry, JobWorker, default_registry
from videocreator.logging_setup import setup_logging
from videocreator.paths import AppPaths, get_paths
from videocreator.scheduler import AppScheduler
from videocreator.secrets_store import SecretsStore
from videocreator.studio.session import recover_stuck_studio_sessions
from videocreator.tg.bot_service import TelegramBotService

logger = logging.getLogger("videocreator.app")


def create_app(
    data_dir: Path | str | None = None,
    *,
    start_worker: bool = True,
    job_registry: JobRegistry = default_registry,
    bind_host: str | None = None,
) -> FastAPI:
    paths: AppPaths = get_paths(data_dir)
    migrate(paths.db_file)
    secrets = SecretsStore(paths.secrets_file)
    setup_logging(paths.log_file, secrets_store=secrets)
    initial_settings = load_settings(paths.config_file)  # writes config.toml with defaults on first run

    register_job_handlers(job_registry, paths)

    worker = JobWorker(
        paths.db_file,
        registry=job_registry,
        io_concurrency=initial_settings.worker.io_concurrency,
        compute_concurrency=initial_settings.worker.compute_concurrency,
    )
    tg_service = TelegramBotService(paths, secrets)
    scheduler = AppScheduler(paths)

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
        tg_task = None
        if current_settings.role == "server" and start_worker:
            import asyncio

            worker.start()
            scheduler.start()
            tg_task = asyncio.create_task(tg_service.start())
        try:
            yield
        finally:
            if tg_task is not None and not tg_task.done():
                tg_task.cancel()
                try:
                    await tg_task
                except BaseException:
                    pass
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
        bind_host=bind_host,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=initial_settings.web_ui.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if paths.static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(paths.static_dir)), name="static")

    app.include_router(dashboard_router)
    app.include_router(settings_router)
    app.include_router(config_bundle_router)
    app.include_router(products_router)
    app.include_router(footage_router)
    app.include_router(shots_router)
    app.include_router(media_router)
    app.include_router(planning_router)
    app.include_router(videos_router)
    app.include_router(ai_router)
    app.include_router(assets_router)
    app.include_router(approval_router)
    app.include_router(accounts_router)
    app.include_router(posting_router)
    app.include_router(performance_router)
    app.include_router(oauth_router)
    app.include_router(watchlist_router)
    app.include_router(trends_router)
    app.include_router(suggestions_router)
    app.include_router(broll_router)
    app.include_router(manual_router)
    app.include_router(voices_router)
    app.include_router(studio_router)
    app.include_router(v1_router)

    return app
