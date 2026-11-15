"""Database side of the planner: source shots, existing plans for deduplication, saving a plan."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any

from videocreator.db import query_all, query_one
from videocreator.jsonutil import parse_int_list, parse_str_list
from videocreator.paths import AppPaths


LIBRARY_SHOT_LIMIT = 40


def _shot_products(row: dict[str, Any]) -> list[int]:
    return parse_int_list(row.get("product_ids_json"))


def select_library_shots(
    rows: list[dict[str, Any]],
    preferred_ids: list[int] | None,
    limit: int = LIBRARY_SHOT_LIMIT,
    *,
    collection: bool = False,
) -> list[dict[str, Any]]:
    """Picks at most `limit` library shots for one script request; `rows` are ordered best first.

    With suggested shots, the script stays on their main product: those shots first, then other
    shots of that product and shots without a product. Without them, product groups take turns so
    every product is represented. A collection formula may mix products, so no product filter."""
    by_id = {int(r["id"]): r for r in rows}
    preferred = [by_id[i] for i in (preferred_ids or []) if i in by_id]
    if preferred and not collection:
        counts: dict[int, int] = {}
        for r in preferred:
            for pid in _shot_products(r):
                counts[pid] = counts.get(pid, 0) + 1
        focus = max(counts, key=lambda p: counts[p]) if counts else None
        chosen = [r for r in preferred if focus is None or not _shot_products(r) or focus in _shot_products(r)]
        chosen_ids = {int(r["id"]) for r in chosen}
        for r in rows:
            if len(chosen) >= limit:
                break
            pids = _shot_products(r)
            if int(r["id"]) not in chosen_ids and (not pids or focus is None or focus in pids):
                chosen.append(r)
        return chosen[:limit]

    groups: dict[int | None, list[dict[str, Any]]] = {}
    for r in preferred + rows:
        pids = _shot_products(r)
        groups.setdefault(pids[0] if pids else None, []).append(r)
    chosen, seen = [], set()
    while len(chosen) < limit and any(groups.values()):
        for key in list(groups):
            if not groups[key] or len(chosen) >= limit:
                continue
            r = groups[key].pop(0)
            if int(r["id"]) not in seen:
                seen.add(int(r["id"]))
                chosen.append(r)
    return chosen


def load_source_shots(
    paths: AppPaths,
    footage_id: int | None,
    *,
    preferred_shot_ids: list[int] | None = None,
    collection: bool = False,
) -> list[dict[str, Any]]:
    """Shots of one footage, or a focused part of the shot library when `footage_id` is None.

    Library mode offers described shots (the writer can see what they show) and at most
    `LIBRARY_SHOT_LIMIT` of them, see `select_library_shots`. Shots a suggestion recommends are
    kept even if undescribed; a library with no description at all falls back to every shot."""
    if footage_id is None:
        all_shots = query_all(paths.db_file, "SELECT * FROM shots ORDER BY quality DESC, id ASC")
        if not all_shots:
            raise ValueError("Kho shot hiện đang trống; hãy nạp và phân tích footage trước")
        wanted = set(preferred_shot_ids or [])
        described = [
            r for r in all_shots if str(r.get("description") or "").strip() or int(r["id"]) in wanted
        ]
        return select_library_shots(described or all_shots, preferred_shot_ids, collection=collection)
    footage = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (footage_id,))
    if footage is None:
        raise LookupError(f"Footage #{footage_id} not found")
    raw_shots = query_all(
        paths.db_file,
        "SELECT * FROM shots WHERE footage_id = ? ORDER BY idx ASC",
        (footage_id,),
    )
    if not raw_shots:
        raise ValueError(f"Footage #{footage_id} has no shots; run analyse first")
    return raw_shots


def with_parsed_lists(shot_row: dict[str, Any]) -> dict[str, Any]:
    """Adds `product_ids` and `tags` parsed from the row's JSON columns."""
    product_ids = parse_int_list(shot_row.get("product_ids_json"))
    tags = parse_str_list(shot_row.get("tags_json"))
    return {**shot_row, "product_ids": product_ids, "tags": tags}


def existing_plan_index(db_file: Path, shot_ids: set[int]) -> tuple[list[set[int]], set[str]]:
    """Shot sets and formulas of live videos sharing any of `shot_ids` (for Jaccard deduplication)."""
    existing_sets: list[set[int]] = []
    existing_formulas: set[str] = set()
    existing_videos = query_all(
        db_file,
        "SELECT plan_json FROM videos WHERE status != 'rejected' AND status != 'superseded'",
    )
    for video in existing_videos:
        try:
            plan = json.loads(video.get("plan_json") or "{}")
            plan_shot_ids = {int(x["shot_id"]) for x in plan.get("shots", []) if "shot_id" in x}
            if not plan_shot_ids & shot_ids:
                continue
            existing_sets.append(plan_shot_ids)
            if plan.get("formula"):
                existing_formulas.add(str(plan["formula"]).lower())
        except Exception:
            continue
    return existing_sets, existing_formulas


def save_plan(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    replace_video_id: int | None,
    suggestion_id: int | None,
    auto_render: bool,
) -> int:
    """Writes a validated plan into the `planned` row being redone, or into a new `videos` row."""
    product_ids_json = json.dumps(plan["product_ids"])
    plan_json = json.dumps(plan, ensure_ascii=False)
    captions_json = json.dumps(plan["captions"], ensure_ascii=False)
    claims_json = json.dumps(plan["unverified_claims"], ensure_ascii=False)
    if replace_video_id is not None:
        conn.execute(
            """
            UPDATE videos
            SET product_ids_json = ?, plan_json = ?, captions_json = ?, unsupported_claims_json = ?
            WHERE id = ? AND status = 'planned'
            """,
            (product_ids_json, plan_json, captions_json, claims_json, replace_video_id),
        )
        return int(replace_video_id)
    default_engine = "mpt" if plan["voice_lang"] in ("vi", "en") else "ffmpeg"
    cur = conn.execute(
        """
        INSERT INTO videos (
            footage_id, product_ids_json, engine, status, plan_json,
            voice_lang, caption_lang, captions_json, unsupported_claims_json,
            suggestion_id, auto_render
        )
        VALUES (?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan["footage_id"],
            product_ids_json,
            default_engine,
            plan_json,
            plan["voice_lang"],
            plan["caption_lang"],
            captions_json,
            claims_json,
            suggestion_id,
            1 if auto_render else 0,
        ),
    )
    return int(cur.lastrowid or 0)
