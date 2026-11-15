"""The brief of a Studio session: shots, footage files and product facts the agent may use."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from videocreator.db import query_all, query_one
from videocreator.jsonutil import loads_or, parse_int_list
from videocreator.paths import AppPaths

MAX_BRIEF_SHOTS = 60


def build_brief(paths: AppPaths, user_prompt: str, options: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Path]]:
    """Collects the shots, footage files and product facts the agent may use."""
    sql = """
        SELECT s.id, s.start_s, s.end_s, s.description, s.has_product, s.quality,
               f.id AS footage_id, f.path AS footage_path, f.product_ids_json
        FROM shots s JOIN footage f ON s.footage_id = f.id
    """
    shot_ids = [int(x) for x in options.get("shot_ids") or []]
    params: list[Any] = []
    if shot_ids:
        sql += f" WHERE s.id IN ({','.join('?' * len(shot_ids))})"
        params.extend(shot_ids)
    sql += " ORDER BY s.quality DESC, s.id ASC LIMIT ?"
    params.append(MAX_BRIEF_SHOTS)
    rows = query_all(paths.db_file, sql, params)
    footage_files: dict[str, Path] = {}
    shots: list[dict[str, Any]] = []
    product_ids: set[int] = set()
    for r in rows:
        source = paths.media_dir / str(r["footage_path"])
        if not source.exists():
            continue
        name = f"footage_{int(r['footage_id'])}{source.suffix.lower()}"
        footage_files[name] = source
        ids = parse_int_list(r.get("product_ids_json"))
        product_ids.update(ids)
        shots.append(
            {
                "shot_id": int(r["id"]),
                "file": name,
                "start_s": float(r["start_s"]),
                "end_s": float(r["end_s"]),
                "description": str(r.get("description") or ""),
                "has_product": bool(r.get("has_product")),
                "product_ids": ids,
            }
        )
    products: list[dict[str, Any]] = []
    for pid in sorted(product_ids):
        p = query_one(paths.db_file, "SELECT * FROM products WHERE id = ? AND hidden = 0", (pid,))
        if p is not None:
            facts = loads_or(p.get("facts_json"), {})
            products.append({"id": pid, "name": p["name"], "material": p.get("material"), "facts": facts})
    voice_lang = str(options.get("voice_lang") or "none")
    brief = {
        "request": user_prompt,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "voice_over": voice_lang,
        "background_music": bool(options.get("music_asset_id")),
        "shots": shots,
        "products": products,
    }
    return brief, footage_files
