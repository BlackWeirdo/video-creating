"""Versioned JSON REST API router (`/api/v1`)."""
from __future__ import annotations

from fastapi import APIRouter

from videocreator.api.v1.routes_jobs import router as jobs_router
from videocreator.api.v1.routes_system import router as system_router
from videocreator.api.v1.routes_workspaces import router as workspaces_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(system_router)
v1_router.include_router(workspaces_router)
v1_router.include_router(jobs_router)
