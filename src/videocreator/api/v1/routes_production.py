"""Aggregator router for `/api/v1` production endpoints (`styles`, `videos`, `studio/sessions`)."""
from __future__ import annotations

from fastapi import APIRouter

from videocreator.api.v1.routes_studio_sessions_v1 import router as studio_sessions_v1_router
from videocreator.api.v1.routes_styles_v1 import router as styles_v1_router
from videocreator.api.v1.routes_videos_v1 import router as videos_v1_router

router = APIRouter()
router.include_router(styles_v1_router)
router.include_router(videos_v1_router)
router.include_router(studio_sessions_v1_router)

__all__ = ["router"]
