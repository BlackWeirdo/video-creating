"""Safe media file serving (`NFR-SEC-05`)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from videocreator.paths import AppPaths

router = APIRouter()


@router.get("/media/{subpath:path}")
@router.get("/files/{subpath:path}")
async def serve_media(request: Request, subpath: str) -> FileResponse:
    """Safely serves media files inside `paths.media_dir` with Range support, blocking traversal (NFR-SEC-05)."""
    paths: AppPaths = request.app.state.paths
    media_root = paths.media_dir.resolve()
    if ".." in Path(subpath).parts:
        raise HTTPException(status_code=403, detail="Path traversal forbidden")
    target = (media_root / subpath).resolve()
    if not target.is_relative_to(media_root) or not target.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(target)
