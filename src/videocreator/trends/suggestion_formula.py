"""The formula a suggestion hands to the script writer, with the analysis of its reference video."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from videocreator.db import query_one
from videocreator.jsonutil import loads_or

# Fields of `TrendAnalysisSchema` (`trends/analyse.py`) the writer needs to follow the reference video.
ANALYSIS_KEYS: tuple[str, ...] = ("hook", "structure", "cut_pace_s", "text_style", "music_mood", "why_it_works")
MAX_TEXT_CHARS = 300
MAX_BEATS = 12


def _clip(value: Any) -> Any:
    return value[:MAX_TEXT_CHARS] if isinstance(value, str) else value


def trim_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """The writer-relevant part of a trend analysis, with bounded length (it is external content)."""
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
    """`suggestions.formula_json` plus `trend_analysis` read from the linked trend item.

    The analysis is read at use time rather than copied into the suggestion, so suggestions saved
    before this existed get it too. Returns None when the suggestion does not exist."""
    row = query_one(
        db_file,
        """
        SELECT s.formula_json, t.analysis_json
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
    analysis = loads_or(row.get("analysis_json"), {})
    if isinstance(analysis, dict):
        trimmed = trim_analysis(analysis)
        if trimmed:
            formula["trend_analysis"] = trimmed
    return formula
