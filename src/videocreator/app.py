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
from videocreator.api.legacy_v1 import include_legacy_v1_and_core_mounts
from videocreator.api.mounts import freecut_router, ui_fallback_router
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

    include_legacy_v1_and_core_mounts(app)
    app.include_router(v1_router)
    app.include_router(freecut_router)
    app.include_router(ui_fallback_router)

    return app
