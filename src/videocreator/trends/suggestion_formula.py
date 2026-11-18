"""The formula a suggestion hands to the script writer, with the analysis of its reference video."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from videocreator.db import query_one
from videocreator.jsonutil import loads_or

# Fields of `TrendAnalysisSchema` (`trends/analyse.py`) passed downstream to planner / Studio / renderer.
ANALYSIS_KEYS: tuple[str, ...] = (
    "hook",
    "structure",
    "cut_pace_s",
    "text_style",
    "music_mood",
    "why_it_works",
    "analysis_mode",
    "reference_duration_s",
    "audio_mode",
    "hook_layout",
    "energy_level",
)
MAX_TEXT_CHARS = 300
MAX_BEATS = 12


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_TEXT_CHARS]
    if isinstance(value, list):
        return [_clip(x) for x in value[:8]]
    return value


def trim_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """The writer/editor-relevant part of a trend analysis, with bounded length (external content)."""
    out: dict[str, Any] = {}
    for key in ANALYSIS_KEYS:
        if analysis.get(key) in (None, "", []):
            continue
        if key == "structure" and isinstance(analysis[key], list):
            out[key] = [
                {k: _clip(v) for k, v in beat.items()} if isinstance(beat, dict) else _clip(beat)
                for beat in analysis[key][:MAX_BEATS]
            ]
        else:
            out[key] = _clip(analysis[key])
    return out


def load_suggestion_formula(db_file: Path, suggestion_id: int) -> dict[str, Any] | None:
    """`suggestions.formula_json` plus `trend_analysis` and `trend_item_id` read from the linked trend item."""
    row = query_one(
        db_file,
        """
        SELECT s.trend_item_id, s.formula_json, t.analysis_json
        FROM suggestions s
        LEFT JOIN trend_items t ON t.id = s.trend_item_id
        WHERE s.id = ?
        """,
        (suggestion_id,),
    )
    if row is None:
        return None
    formula = loads_or(row.get("formula_json"), {})
    if not isinstance(formula, dict):
        formula = {"formula": str(formula)}
    if row.get("trend_item_id") is not None:
        formula["trend_item_id"] = int(row["trend_item_id"])
    analysis = loads_or(row.get("analysis_json"), {})
    if isinstance(analysis, dict):
        trimmed = trim_analysis(analysis)
        if trimmed:
            formula["trend_analysis"] = trimmed
    return formula
