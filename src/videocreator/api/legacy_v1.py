"""Isolated registration for deprecated V1 Jinja2/HTMX routers & ordered root mounts.

Keeping V1 HTML router wiring isolated here keeps `videocreator.app` clean while
preserving the exact FastAPI route registration order verified by `tests/snapshots/routes.json`.
"""
from __future__ import annotations

from fastapi import FastAPI

from videocreator.api.mounts import (
    config_bundle_router,
    media_router,
    oauth_router,
)
from videocreator.api.routes_accounts import router as accounts_router
from videocreator.api.routes_ai import router as ai_router
from videocreator.api.routes_approval import router as approval_router
from videocreator.api.routes_assets import router as assets_router
from videocreator.api.routes_broll import router as broll_router
from videocreator.api.routes_dashboard import router as dashboard_router
from videocreator.api.routes_footage import router as footage_router
from videocreator.api.routes_manual import router as manual_router
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


def include_legacy_v1_and_core_mounts(app: FastAPI) -> None:
    """Register root mounts (`config_bundle`, `media`, `oauth`) and legacy V1 HTML routers in exact snapshot order."""
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
