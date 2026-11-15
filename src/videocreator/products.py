"""Product catalog: the only source of product facts for scripts and captions (`BR-PRD-04`)."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or


def _parse_product_row(row: dict[str, Any]) -> dict[str, Any]:
    facts = loads_or(row.get("facts_json"), {})
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


def product_name_map(db_file: Path) -> dict[int, str]:
    """`{product_id: name}` of every product, hidden ones included (old videos still reference them)."""
    return {p["id"]: p["name"] for p in list_products(db_file, include_hidden=True)}

