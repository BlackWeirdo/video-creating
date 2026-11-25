"""Workspace-scoped Products CRUD endpoints for `/api/v1`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.paths import AppPaths
from videocreator.products import (
    create_product,
    delete_or_hide_product,
    get_product,
    list_products,
    update_product,
)

router = APIRouter()


class ProductCreateBody(BaseModel):
    workspace_id: int | None = None
    name: str
    material: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)


class ProductUpdateBody(BaseModel):
    name: str | None = None
    material: str | None = None
    facts: dict[str, Any] | None = None


@router.get("/products")
async def api_v1_list_products(
    request: Request,
    workspace_id: int | None = Query(default=None),
    include_hidden: bool = Query(default=False),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    items = list_products(paths.db_file, include_hidden=include_hidden, workspace_id=ws_id)
    return JSONResponse({"products": items, "workspace_id": ws_id})


@router.post("/products", status_code=201)
async def api_v1_create_product(request: Request, body: ProductCreateBody) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    try:
        pid = create_product(
            paths.db_file,
            name=body.name,
            material=body.material,
            facts=body.facts,
            workspace_id=ws_id,
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"product": get_product(paths.db_file, pid)}, status_code=201)


@router.patch("/products/{product_id}")
async def api_v1_update_product(
    request: Request, product_id: int, body: ProductUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    existing = get_product(paths.db_file, product_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Product #{product_id} not found")
    try:
        update_product(
            paths.db_file,
            product_id,
            name=body.name if body.name is not None else str(existing["name"]),
            material=body.material if body.material is not None else str(existing["material"]),
            facts=body.facts if body.facts is not None else dict(existing["facts"]),
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"product": get_product(paths.db_file, product_id)})


@router.delete("/products/{product_id}")
async def api_v1_delete_product(request: Request, product_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    existing = get_product(paths.db_file, product_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Product #{product_id} not found")
    outcome = delete_or_hide_product(paths.db_file, product_id, actor="api")
    return JSONResponse({"outcome": outcome, "product_id": product_id})
