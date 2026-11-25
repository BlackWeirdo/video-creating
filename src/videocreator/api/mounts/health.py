"""Root `/health` probe mount shared by desktop launcher, Docker/LAN checks, and V2 runtime."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.paths import AppPaths

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    return JSONResponse(
        {
            "status": "ok",
            "role": cfg.role,
            "version": __version__,
        }
    )


__all__ = ["router"]
