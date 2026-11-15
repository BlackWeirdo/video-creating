"""What the B-roll idea writer is told: products, shot library, trend analyses, reference look."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from videocreator.db import query_all, query_one
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.broll import list_broll_shots
from videocreator.pipeline.broll_ideas import MAX_FIELD_CHARS
from videocreator.trends.suggest import summarize_shot_library

MAX_LOOK_CHARS = 1500
MAX_TRENDS_IN_CONTEXT = 5


def read_reference_look(media_dir: Path, rea_dir: str | None) -> str:
    """Returns the measured "Camera, lighting and editing" block of a rea-video `look.md`, or ''."""
    if not rea_dir:
        return ""
    base = media_dir.resolve()
    look_file = (media_dir / rea_dir / "video" / "look.md").resolve()
    if base not in look_file.parents or not look_file.is_file():
        return ""
    text = look_file.read_text(encoding="utf-8", errors="replace")
    start = text.find("## Camera, lighting and editing")
    if start < 0:
        return ""
    block = text[start + len("## Camera, lighting and editing"):]
    end = block.find("**Shooting plan")
    if end >= 0:
        block = block[:end]
    return block.strip()[:MAX_LOOK_CHARS]


def build_broll_context(paths: AppPaths) -> dict[str, Any]:
    """Collects the analysis data the AI needs to propose B-roll that fits the trends and fills footage gaps."""
    db_file = paths.db_file
    trend_rows = query_all(
        db_file,
        """
        SELECT t.id, t.source, t.author, t.score, t.analysis_json, rv.rea_dir
        FROM trend_items t
        LEFT JOIN reference_videos rv ON rv.trend_item_id = t.id
        WHERE t.analysis_json IS NOT NULL AND t.analysis_json != ''
        ORDER BY t.score DESC, t.id ASC
        LIMIT ?
        """,
        (MAX_TRENDS_IN_CONTEXT,),
    )
    trends = []
    for r in trend_rows:
        analysis = loads_or(r.get("analysis_json"), {})
        trends.append(
            {
                "trend_item_id": int(r["id"]),
                "source": r["source"],
                "author": r["author"],
                "hook": str(analysis.get("hook", ""))[:MAX_FIELD_CHARS],
                "structure": analysis.get("structure", [])[:12],
                "cut_pace_s": analysis.get("cut_pace_s"),
                "music_mood": str(analysis.get("music_mood", ""))[:MAX_FIELD_CHARS],
                "why_it_works": str(analysis.get("why_it_works", ""))[:MAX_FIELD_CHARS],
                # Measured by rea-video on the reference file (framing, camera, lighting, grade).
                "look": read_reference_look(paths.media_dir, r.get("rea_dir")),
            }
        )

    sug_rows = query_all(
        db_file,
        """
        SELECT id, trend_item_id, text, formula_json
        FROM suggestions
        WHERE status IN ('new', 'sent', 'accepted')
        ORDER BY id DESC
        LIMIT 5
        """,
    )
    suggestions = []
    for r in sug_rows:
        formula = loads_or(r.get("formula_json"), {})
        suggestions.append(
            {
                "suggestion_id": int(r["id"]),
                "trend_item_id": r.get("trend_item_id"),
                "text": str(r.get("text") or "")[:300],
                "formula": formula.get("formula", ""),
                "missing_shots": formula.get("missing_shots", ""),
            }
        )

    existing_broll = [
        str(s.get("description") or "")[:160] for s in list_broll_shots(db_file)[:20]
    ]
    # Hidden products are still real products: include them so the name filter covers them too.
    products = [
        {"name": str(p["name"]), "material": str(p.get("material") or "")}
        for p in query_all(db_file, "SELECT name, material FROM products ORDER BY id")
    ]
    footage_row = query_one(
        db_file, "SELECT COUNT(*) AS c FROM shots WHERE footage_id IS NOT NULL"
    )
    return {
        "trends": trends,
        "suggestions": suggestions,
        "footage": summarize_shot_library(db_file),
        "footage_shot_count": int(footage_row["c"]) if footage_row else 0,
        "existing_broll": existing_broll,
        "products": products,
    }
