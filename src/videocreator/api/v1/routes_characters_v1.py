"""Characters & AI Image Studio endpoints for `/api/v1`."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.paths import AppPaths
from videocreator.pipeline.channel_voices import (
    create_channel_voice,
    delete_channel_voice,
    list_channel_voices,
)
from videocreator.pipeline.characters import (
    animate_image_to_shot,
    create_character,
    cutout_ai_image,
    cutout_character,
    delete_character,
    generate_ai_image,
    get_character,
    list_ai_images,
    list_characters,
    save_character_ref_image,
    update_character,
)

router = APIRouter()


class CharacterCreateBody(BaseModel):
    workspace_id: int | None = None
    name: str
    appearance_prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    voice_id: str = "vi-VN-HoaiMyNeural"
    style_tags: list[str] = Field(default_factory=list)


class CharacterPatchBody(BaseModel):
    name: str | None = None
    appearance_prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    voice_id: str | None = None
    style_tags: list[str] | None = None


class AIImageGenerateBody(BaseModel):
    workspace_id: int | None = None
    character_id: int | None = None
    prompt: str
    seed: int | None = None
    aspect_ratio: str = "9:16"
    is_product_shot: bool = False
    animate_to_shot: bool = True


@router.get("/characters")
async def api_v1_list_characters(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {
            "characters": list_characters(paths.db_file, workspace_id=ws_id),
            "workspace_id": ws_id,
        }
    )


@router.post("/characters", status_code=201)
async def api_v1_create_character(
    request: Request, body: CharacterCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        ch = create_character(
            paths,
            workspace_id=ws_id,
            name=body.name,
            appearance_prompt=body.appearance_prompt,
            negative_prompt=body.negative_prompt,
            seed=body.seed,
            voice_id=body.voice_id,
            style_tags=body.style_tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"character": ch}, status_code=201)


@router.patch("/characters/{character_id}")
async def api_v1_patch_character(
    request: Request, character_id: int, body: CharacterPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ch = update_character(
        paths,
        character_id,
        name=body.name,
        appearance_prompt=body.appearance_prompt,
        negative_prompt=body.negative_prompt,
        seed=body.seed,
        voice_id=body.voice_id,
        style_tags=body.style_tags,
    )
    if ch is None:
        raise HTTPException(status_code=404, detail=f"Character #{character_id} not found")
    return JSONResponse({"character": ch})


@router.delete("/characters/{character_id}")
async def api_v1_delete_character(request: Request, character_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    if not delete_character(paths, character_id):
        raise HTTPException(status_code=404, detail=f"Character #{character_id} not found")
    return JSONResponse({"ok": True, "deleted_id": character_id})


@router.post("/characters/{character_id}/upload-ref")
async def api_v1_upload_character_ref(
    request: Request,
    character_id: int,
    file: UploadFile = File(...),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    raw = await file.read()
    try:
        ch = save_character_ref_image(
            paths, character_id, filename=file.filename or "ref.png", data=raw
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"character": ch})


@router.post("/characters/{character_id}/cutout")
async def api_v1_cutout_character(
    request: Request, character_id: int
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    if get_character(paths.db_file, character_id) is None:
        raise HTTPException(status_code=404, detail=f"Character #{character_id} not found")
    try:
        ch = cutout_character(paths, character_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"character": ch})


@router.get("/images")
async def api_v1_list_images(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {
            "images": list_ai_images(paths.db_file, workspace_id=ws_id),
            "workspace_id": ws_id,
        }
    )


@router.post("/images", status_code=201)
async def api_v1_generate_image(
    request: Request, body: AIImageGenerateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        img = generate_ai_image(
            paths,
            workspace_id=ws_id,
            prompt=body.prompt,
            character_id=body.character_id,
            seed=body.seed,
            aspect_ratio=body.aspect_ratio,
            is_product_shot=body.is_product_shot,
            animate_to_shot=body.animate_to_shot,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"image": img}, status_code=201)


@router.post("/images/{image_id}/cutout")
async def api_v1_cutout_image(request: Request, image_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        img = cutout_ai_image(paths, image_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"image": img})


@router.post("/images/{image_id}/animate")
async def api_v1_animate_image(request: Request, image_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        img = animate_image_to_shot(paths, image_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"image": img})


@router.get("/channel-voices")
async def api_v1_list_channel_voices(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {
            "channel_voices": list_channel_voices(paths.db_file, workspace_id=ws_id),
            "workspace_id": ws_id,
        }
    )


@router.post("/channel-voices", status_code=201)
async def api_v1_create_channel_voice(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    speaker_name: str = Form(...),
    consent_confirmed: bool = Form(False),
    workspace_id: int | None = Form(default=None),
    character_id: int | None = Form(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    raw = await file.read()
    try:
        cv = create_channel_voice(
            paths,
            workspace_id=ws_id,
            name=name,
            speaker_name=speaker_name,
            consent_confirmed=bool(consent_confirmed),
            raw_audio_bytes=raw,
            filename=file.filename or "sample.wav",
            character_id=character_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"channel_voice": cv}, status_code=201)


@router.delete("/channel-voices/{voice_id}")
async def api_v1_delete_channel_voice(request: Request, voice_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    if not delete_channel_voice(paths, voice_id):
        raise HTTPException(status_code=404, detail=f"Channel voice #{voice_id} not found")
    return JSONResponse({"ok": True, "deleted_id": voice_id})
