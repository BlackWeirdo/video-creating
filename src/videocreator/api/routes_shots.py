"""Shot library page and shot editing routes (Phase 03)."""
from __future__ import annotations
import json
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, record_audit
from videocreator.jsonutil import parse_int_list, parse_str_list
from videocreator.paths import AppPaths
from videocreator.products import list_products
from videocreator.templating import get_templates

router = APIRouter()


@router.get("/shots", response_class=HTMLResponse)
async def shots_page(
    request: Request,
    footage_id: int | None = None,
    product_id: int | None = None,
    tag: str | None = None,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = get_templates(paths)

    all_products = list_products(paths.db_file, include_hidden=True)
    active_products = [p for p in all_products if not p["hidden"]]
    product_map = {p["id"]: p["name"] for p in all_products}
    footage_list = query_all(paths.db_file, "SELECT id, path, status FROM footage ORDER BY id DESC")

    sql = """
        SELECT s.*, f.path AS footage_path
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        WHERE 1=1
    """
    params: list[Any] = []
    if footage_id is not None:
        sql += " AND s.footage_id = ?"
        params.append(footage_id)
    sql += " ORDER BY s.footage_id DESC, s.idx ASC"

    raw_shots = query_all(paths.db_file, sql, params)
    shots: list[dict[str, Any]] = []
    all_tags: set[str] = set()
    for r in raw_shots:
        pids = parse_int_list(r.get("product_ids_json"))
        tags = parse_str_list(r.get("tags_json"))
        for t in tags:
            all_tags.add(t)

        if product_id is not None and product_id not in pids:
            continue
        if tag and tag.strip() and tag.strip() not in tags:
            continue

        shots.append(
            {
                **r,
                "duration_s": round(float(r["end_s"]) - float(r["start_s"]), 2),
                "product_ids": pids,
                "product_names": [product_map.get(pid, f"#{pid}") for pid in pids],
                "tags": tags,
                "tags_str": ", ".join(tags),
            }
        )

    return templates.TemplateResponse(
        request,
        "shots.html",
        {
            "page": "shots",
            "settings": cfg,
            "shots": shots,
            "products": active_products,
            "footage_list": footage_list,
            "all_tags": sorted(all_tags),
            "filter_footage_id": footage_id,
            "filter_product_id": product_id,
            "filter_tag": tag or "",
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/shots/{shot_id}/update")
async def update_shot(
    request: Request,
    shot_id: int,
    product_ids: list[int] = Form(default=[]),
    no_product: bool = Form(default=False),
    tags: str = Form(""),
    description: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    clean_pids = [] if no_product else sorted({int(x) for x in product_ids if int(x) > 0})
    has_product = 0 if (no_product or not clean_pids) else 1
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            UPDATE shots
            SET has_product = ?,
                product_ids_json = ?,
                tags_json = ?,
                description = ?
            WHERE id = ?
            """,
            (
                has_product,
                json.dumps(clean_pids),
                json.dumps(tag_list, ensure_ascii=False),
                description.strip(),
                shot_id,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Shot not found")
        record_audit(
            conn,
            actor="ui",
            action="shot.updated",
            object_type="shot",
            object_id=shot_id,
            detail=f"has_product={has_product}, products={clean_pids}",
        )
    return RedirectResponse(url="/shots?msg=updated", status_code=303)
