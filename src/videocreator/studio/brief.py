"""The brief of a Studio session: shots, footage files and product facts the agent may use."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from videocreator.db import query_all, query_one
from videocreator.jsonutil import loads_or, parse_int_list
from videocreator.paths import AppPaths

MAX_BRIEF_SHOTS = 60


def _load_music_brief(paths: AppPaths, music_asset_id: Any) -> dict[str, Any] | None:
    if not music_asset_id:
        return None
    row = query_one(
        paths.db_file,
        "SELECT id, path, duration_s, meta_json FROM assets WHERE id = ? AND kind = 'music'",
        (int(music_asset_id),),
    )
    if row is None:
        return None
    meta = loads_or(row.get("meta_json"), {})
    if not isinstance(meta, dict):
        meta = {}
    full = paths.media_dir / str(row["path"])
    if "beat_times_s" not in meta and full.is_file():
        try:
            import json
            from videocreator.db import get_conn
            from videocreator.pipeline.audio_beats import analyse_music_beats

            meta = {**meta, **analyse_music_beats(full)}
            with get_conn(paths.db_file) as conn:
                conn.execute("UPDATE assets SET meta_json = ? WHERE id = ?", (json.dumps(meta, ensure_ascii=False), int(row["id"])))
        except Exception:
            pass
    return {
        "asset_id": int(row["id"]),
        "duration_s": float(row.get("duration_s") or 0.0),
        "bpm": meta.get("bpm"),
        "energy_level": meta.get("energy_level"),
        "mood_tags": list(meta.get("mood_tags") or []),
        "beat_times_s": list(meta.get("beat_times_s") or [])[:60],
        "strong_beats_s": list(meta.get("strong_beats_s") or [])[:24],
    }


def _resolve_trend_context(
    paths: AppPaths,
    options: dict[str, Any],
    ref_item_id: int | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    from videocreator.trends.suggestion_formula import load_suggestion_formula, trim_analysis

    blueprint: dict[str, Any] | None = None
    beat_map: list[dict[str, Any]] | None = None

    opt_bp = options.get("trend_blueprint")
    if isinstance(opt_bp, dict) and opt_bp:
        blueprint = trim_analysis(opt_bp) or opt_bp

    opt_map = options.get("beat_shot_map")
    if isinstance(opt_map, list) and opt_map:
        beat_map = opt_map

    sug_id = options.get("suggestion_id")
    if sug_id:
        f_obj = load_suggestion_formula(paths.db_file, int(sug_id)) or {}
        if not blueprint and isinstance(f_obj.get("trend_analysis"), dict):
            blueprint = f_obj["trend_analysis"]
        if not beat_map and isinstance(f_obj.get("beat_shot_map"), list) and f_obj["beat_shot_map"]:
            beat_map = f_obj["beat_shot_map"]

    if not blueprint and ref_item_id:
        t_row = query_one(paths.db_file, "SELECT analysis_json FROM trend_items WHERE id = ?", (int(ref_item_id),))
        if t_row is not None:
            trimmed = trim_analysis(loads_or(t_row.get("analysis_json"), {}))
            if trimmed:
                blueprint = trimmed

    return blueprint, beat_map


def build_brief(
    paths: AppPaths,
    user_prompt: str,
    options: dict[str, Any],
    *,
    ref_item_id: int | None = None,
) -> tuple[dict[str, Any], dict[str, Path]]:
    """Collects the shots, footage files, trend blueprint, music beat grid and product facts."""
    sql = """
        SELECT s.id, s.start_s, s.end_s, s.description, s.tags_json, s.has_product, s.quality,
               s.product_ids_json AS shot_product_ids_json,
               s.asset_id,
               f.id AS footage_id, f.path AS footage_path,
               f.product_ids_json AS footage_product_ids_json,
               a.path AS asset_path
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE (f.path IS NOT NULL OR a.path IS NOT NULL)
    """
    shot_ids = [int(x) for x in options.get("shot_ids") or []]
    params: list[Any] = []
    if shot_ids:
        sql += f" AND s.id IN ({','.join('?' * len(shot_ids))})"
        params.extend(shot_ids)
    sql += " ORDER BY s.quality DESC, s.id ASC LIMIT ?"
    params.append(MAX_BRIEF_SHOTS)
    rows = query_all(paths.db_file, sql, params)
    footage_files: dict[str, Path] = {}
    shots: list[dict[str, Any]] = []
    product_ids: set[int] = set()
    for r in rows:
        rel_path = r.get("footage_path") or r.get("asset_path")
        if not rel_path:
            continue
        source = paths.media_dir / str(rel_path)
        if not source.exists():
            continue
        if r.get("footage_id") is not None:
            name = f"footage_{int(r['footage_id'])}{source.suffix.lower()}"
        else:
            name = f"asset_{int(r['asset_id'])}{source.suffix.lower()}"
        footage_files[name] = source
        shot_pids = parse_int_list(r.get("shot_product_ids_json"))
        ftg_pids = parse_int_list(r.get("footage_product_ids_json"))
        ids = (shot_pids or ftg_pids) if bool(r.get("has_product")) else shot_pids
        product_ids.update(ids)
        tags = loads_or(r.get("tags_json"), [])
        shots.append(
            {
                "shot_id": int(r["id"]),
                "file": name,
                "start_s": float(r["start_s"]),
                "end_s": float(r["end_s"]),
                "description": str(r.get("description") or ""),
                "tags": tags if isinstance(tags, list) else [],
                "has_product": bool(r.get("has_product")),
                "product_ids": ids,
            }
        )
    products: list[dict[str, Any]] = []
    for pid in sorted(product_ids):
        p = query_one(paths.db_file, "SELECT * FROM products WHERE id = ?", (pid,))
        if p is not None:
            facts = loads_or(p.get("facts_json"), {})
            products.append({"id": pid, "name": p["name"], "material": p.get("material"), "facts": facts})
    voice_lang = str(options.get("voice_lang") or "none")
    brief: dict[str, Any] = {
        "request": user_prompt,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "voice_over": voice_lang,
        "background_music": bool(options.get("music_asset_id")),
        "shots": shots,
        "products": products,
    }
    music_info = _load_music_brief(paths, options.get("music_asset_id"))
    if music_info is not None:
        brief["music"] = music_info
    blueprint, beat_map = _resolve_trend_context(paths, options, ref_item_id)
    if blueprint:
        brief["trend_blueprint"] = blueprint
    if beat_map:
        brief["beat_shot_map"] = beat_map
    return brief, footage_files
