"""Video Style Presets CRUD endpoints for `/api/v1`."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.paths import AppPaths
from videocreator.pipeline.styles import (
    create_style_preset,
    delete_style_preset,
    list_style_presets,
    update_style_preset,
)

router = APIRouter()


class StyleCreateBody(BaseModel):
    name: str
    preset_id: str = ""
    workspace_id: int | None = None
    subtitle_style: str = "karaoke_highlight"
    font_name: str = "Be Vietnam Pro"
    font_size: int = Field(default=58, ge=24, le=120)
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFE082"
    outline_color: str = "#141414"
    box_color: str = "#99121216"
    position: str = "bottom"
    ducking_enabled: bool = True
    music_volume: float = Field(default=0.22, ge=0.0, le=1.0)
    sfx_transition_asset_id: int | None = None
    intro_text: str = ""
    outro_text: str = ""
    motion_preset: str = "none"


class StyleUpdateBody(BaseModel):
    name: str | None = None
    subtitle_style: str | None = None
    font_name: str | None = None
    font_size: int | None = Field(default=None, ge=24, le=120)
    primary_color: str | None = None
    highlight_color: str | None = None
    outline_color: str | None = None
    box_color: str | None = None
    position: str | None = None
    ducking_enabled: bool | None = None
    music_volume: float | None = Field(default=None, ge=0.0, le=1.0)
    sfx_transition_asset_id: int | None = None
    clear_sfx: bool = False
    intro_text: str | None = None
    outro_text: str | None = None
    motion_preset: str | None = None


@router.get("/styles")
async def api_v1_list_styles(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {"styles": list_style_presets(paths.db_file, workspace_id=ws_id), "workspace_id": ws_id}
    )


@router.post("/styles", status_code=201)
async def api_v1_create_style(request: Request, body: StyleCreateBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = (
        resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
        if body.workspace_id is not None
        else None
    )
    try:
        created = create_style_preset(
            paths.db_file,
            name=body.name,
            preset_id=body.preset_id,
            workspace_id=ws_id,
            subtitle_style=body.subtitle_style,
            font_name=body.font_name,
            font_size=body.font_size,
            primary_color=body.primary_color,
            highlight_color=body.highlight_color,
            outline_color=body.outline_color,
            box_color=body.box_color,
            position=body.position,
            ducking_enabled=body.ducking_enabled,
            music_volume=body.music_volume,
            sfx_transition_asset_id=body.sfx_transition_asset_id,
            intro_text=body.intro_text,
            outro_text=body.outro_text,
            motion_preset=body.motion_preset,
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"style": created}, status_code=201)


@router.patch("/styles/{preset_id}")
async def api_v1_update_style(
    request: Request, preset_id: str, body: StyleUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        updated = update_style_preset(
            paths.db_file,
            preset_id,
            name=body.name,
            subtitle_style=body.subtitle_style,
            font_name=body.font_name,
            font_size=body.font_size,
            primary_color=body.primary_color,
            highlight_color=body.highlight_color,
            outline_color=body.outline_color,
            box_color=body.box_color,
            position=body.position,
            ducking_enabled=body.ducking_enabled,
            music_volume=body.music_volume,
            sfx_transition_asset_id=body.sfx_transition_asset_id,
            clear_sfx=body.clear_sfx,
            intro_text=body.intro_text,
            outro_text=body.outro_text,
            motion_preset=body.motion_preset,
            actor="api",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"style": updated})


@router.delete("/styles/{preset_id}")
async def api_v1_delete_style(request: Request, preset_id: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        delete_style_preset(paths.db_file, preset_id, actor="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"deleted": True, "style_id": preset_id})
