"""Aggregator router for `/api/v1` workspace resources (`products`, `footage`/`shots`, `assets`, `voices`)."""
from __future__ import annotations

from fastapi import APIRouter

from videocreator.api.v1.routes_assets_v1 import router as assets_v1_router
from videocreator.api.v1.routes_footage_v1 import router as footage_v1_router
from videocreator.api.v1.routes_products_v1 import router as products_v1_router
from videocreator.api.v1.routes_voices_v1 import router as voices_v1_router

router = APIRouter()
router.include_router(products_v1_router)
router.include_router(footage_v1_router)
router.include_router(assets_v1_router)
router.include_router(voices_v1_router)

__all__ = ["router"]
