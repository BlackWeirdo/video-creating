"""Product management routes (FR-PRD-01..03)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths
from videocreator.products import delete_or_hide_product, get_product, list_products
from videocreator.templating import get_templates

router = APIRouter()


@router.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request,
    edit_id: int | None = None,
    show_hidden: bool = False,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)
    items = list_products(paths.db_file, include_hidden=show_hidden)
    editing = get_product(paths.db_file, edit_id) if edit_id else None
    return templates.TemplateResponse(
        request,
        "products.html",
        {
            "page": "products",
            "settings": cfg,
            "products": items,
            "editing": editing,
            "show_hidden": show_hidden,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/products")
async def save_product(
    request: Request,
    product_id: int | None = Form(None),
    name: str = Form(...),
    material: str = Form(""),
    stone: str = Form(""),
    size: str = Form(""),
    craftsmanship: str = Form(""),
    price: str = Form(""),
    notes: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Product name is required")

    facts = {
        k: v.strip()
        for k, v in {
            "stone": stone,
            "size": size,
            "craftsmanship": craftsmanship,
            "price": price,
            "notes": notes,
        }.items()
        if v and v.strip()
    }
    facts_json = json.dumps(facts, ensure_ascii=False)

    with get_conn(paths.db_file) as conn:
        if product_id:
            cur = conn.execute(
                """
                UPDATE products
                SET name = ?, material = ?, facts_json = ?, hidden = 0
                WHERE id = ?
                """,
                (clean_name, material.strip(), facts_json, product_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Product not found")
            record_audit(
                conn,
                actor="ui",
                action="product.updated",
                object_type="product",
                object_id=product_id,
                detail=clean_name,
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO products (name, material, facts_json)
                VALUES (?, ?, ?)
                """,
                (clean_name, material.strip(), facts_json),
            )
            new_id = int(cur.lastrowid or 0)
            record_audit(
                conn,
                actor="ui",
                action="product.created",
                object_type="product",
                object_id=new_id,
                detail=clean_name,
            )

    return RedirectResponse(url="/products?msg=saved", status_code=303)


@router.post("/products/{product_id}/delete")
async def remove_product(request: Request, product_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    try:
        outcome = delete_or_hide_product(paths.db_file, product_id, actor="ui")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url=f"/products?msg={outcome}", status_code=303)
