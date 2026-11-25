"""Safe media file serving (`NFR-SEC-05`) mounted at `/media/*` and `/files/*`."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from videocreator.paths import AppPaths
from videocreator.safe_paths import UnsafePathError, resolve_within

router = APIRouter()


@router.get("/media/{subpath:path}")
@router.get("/files/{subpath:path}")
async def serve_media(request: Request, subpath: str) -> FileResponse:
    """Safely serves media files inside `paths.media_dir` with Range support, blocking traversal (NFR-SEC-05)."""
    paths: AppPaths = request.app.state.paths
    try:
        target = resolve_within(paths.media_dir, subpath)
    except UnsafePathError as exc:
        raise HTTPException(status_code=403, detail="Path traversal forbidden") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(target)
