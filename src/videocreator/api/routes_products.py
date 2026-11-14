"""Product management routes (FR-PRD-01..03)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import execute, get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths

router = APIRouter()


def _parse_product_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        facts = json.loads(row.get("facts_json") or "{}")
    except json.JSONDecodeError:
        facts = {}
    if not isinstance(facts, dict):
        facts = {}
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "material": str(row.get("material") or ""),
        "hidden": bool(row.get("hidden")),
        "created_at": str(row.get("created_at") or ""),
        "facts": {
            "stone": str(facts.get("stone") or ""),
            "size": str(facts.get("size") or ""),
            "craftsmanship": str(facts.get("craftsmanship") or ""),
            "price": str(facts.get("price") or ""),
            "notes": str(facts.get("notes") or ""),
        },
        "facts_json": json.dumps(facts, ensure_ascii=False),
    }


def list_products(db_file: Path, *, include_hidden: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM products"
    if not include_hidden:
        sql += " WHERE hidden = 0"
    sql += " ORDER BY id DESC"
    return [_parse_product_row(r) for r in query_all(db_file, sql)]


def get_product(db_file: Path, product_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM products WHERE id = ?", (product_id,))
    return _parse_product_row(row) if row else None


def create_product(
    db_file: Path,
    *,
    name: str,
    material: str = "",
    facts: dict[str, Any] | None = None,
    actor: str = "ui",
) -> int:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Product name is required")
    clean_facts = {
        str(k): str(v).strip()
        for k, v in (facts or {}).items()
        if v is not None and str(v).strip()
    }
    facts_json = json.dumps(clean_facts, ensure_ascii=False)
    with get_conn(db_file) as conn:
        cur = conn.execute(
            "INSERT INTO products (name, material, facts_json) VALUES (?, ?, ?)",
            (clean_name, material.strip(), facts_json),
        )
        new_id = int(cur.lastrowid or 0)
        record_audit(
            conn,
            actor=actor,
            action="product.created",
            object_type="product",
            object_id=new_id,
            detail=clean_name,
        )
    return new_id


def update_product(
    db_file: Path,
    product_id: int,
    *,
    name: str,
    material: str = "",
    facts: dict[str, Any] | None = None,
    actor: str = "ui",
) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Product name is required")
    clean_facts = {
        str(k): str(v).strip()
        for k, v in (facts or {}).items()
        if v is not None and str(v).strip()
    }
    facts_json = json.dumps(clean_facts, ensure_ascii=False)
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            UPDATE products
            SET name = ?, material = ?, facts_json = ?, hidden = 0
            WHERE id = ?
            """,
            (clean_name, material.strip(), facts_json, product_id),
        )
        if cur.rowcount == 0:
            raise LookupError(f"Product {product_id} not found")
        record_audit(
            conn,
            actor=actor,
            action="product.updated",
            object_type="product",
            object_id=product_id,
            detail=clean_name,
        )


def is_product_referenced(db_file: Path, product_id: int) -> bool:
    for table in ("footage", "shots", "videos"):
        rows = query_all(db_file, f"SELECT product_ids_json FROM {table}")
        for r in rows:
            try:
                ids = json.loads(r.get("product_ids_json") or "[]")
            except json.JSONDecodeError:
                continue
            if isinstance(ids, list) and product_id in [int(x) for x in ids if str(x).isdigit()]:
                return True
    return False


def delete_or_hide_product(db_file: Path, product_id: int, actor: str = "ui") -> str:
    """Deletes a product if unreferenced, or marks hidden=1 if linked to footage/shots/videos (FR-PRD-02)."""
    existing = query_one(db_file, "SELECT id, name FROM products WHERE id = ?", (product_id,))
    if existing is None:
        raise LookupError(f"Product {product_id} not found")

    referenced = is_product_referenced(db_file, product_id)
    with get_conn(db_file) as conn:
        if referenced:
            conn.execute("UPDATE products SET hidden = 1 WHERE id = ?", (product_id,))
            action = "hidden"
        else:
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            action = "deleted"
        record_audit(
            conn,
            actor=actor,
            action=f"product.{action}",
            object_type="product",
            object_id=product_id,
            detail=str(existing["name"]),
        )
    return action


@router.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request,
    edit_id: int | None = None,
    show_hidden: bool = False,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))
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
