"""Versioned JSON REST API router (`/api/v1`)."""
from __future__ import annotations

from fastapi import APIRouter

from videocreator.api.v1.routes_autopilot_v1 import router as autopilot_v1_router
from videocreator.api.v1.routes_batch_v1 import router as batch_v1_router
from videocreator.api.v1.routes_characters_v1 import router as characters_v1_router
from videocreator.api.v1.routes_jobs import router as jobs_router
from videocreator.api.v1.routes_localize_v1 import router as localize_v1_router
from videocreator.api.v1.routes_models_v1 import router as models_v1_router
from videocreator.api.v1.routes_news_v1 import router as news_v1_router
from videocreator.api.v1.routes_production import router as production_router
from videocreator.api.v1.routes_publishing import router as publishing_router
from videocreator.api.v1.routes_resources import router as resources_router
from videocreator.api.v1.routes_settings_v1 import router as settings_v1_router
from videocreator.api.v1.routes_system import router as system_router
from videocreator.api.v1.routes_trends_v1 import router as trends_v1_router
from videocreator.api.v1.routes_workspaces import router as workspaces_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(system_router)
v1_router.include_router(workspaces_router)
v1_router.include_router(jobs_router)
v1_router.include_router(resources_router)
v1_router.include_router(production_router)
v1_router.include_router(trends_v1_router)
v1_router.include_router(publishing_router)
v1_router.include_router(settings_v1_router)
v1_router.include_router(models_v1_router)
v1_router.include_router(localize_v1_router)
v1_router.include_router(batch_v1_router)
v1_router.include_router(autopilot_v1_router)
v1_router.include_router(characters_v1_router)
v1_router.include_router(news_v1_router)
