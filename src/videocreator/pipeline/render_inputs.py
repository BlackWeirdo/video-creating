"""Inputs of a render: the 9:16 filter of a source shot and the background music pick."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.audio_beats import analyse_music_beats


def build_segment_filter_args(
    *,
    orientation: str,
    width: int,
    height: int,
    crop_cfg: dict[str, Any] | None,
    focus_x: float | None = None,
) -> list[str]:
    """Builds `-vf` or `-filter_complex` arguments to convert a source shot to 1080x1920 30fps without violating BR-PRD-03."""
    if orientation == "landscape" and width > 0 and height > 0:
        mode = str((crop_cfg or {}).get("mode") or "blur_pad")
        if mode in ("crop", "smart_crop"):
            raw_x = (crop_cfg or {}).get("x_offset_ratio")
            if mode == "smart_crop" and focus_x is not None:
                chosen_x = float(focus_x)
            elif focus_x is not None and (raw_x is None or abs(float(raw_x) - 0.5) < 1e-6):
                chosen_x = float(focus_x)
            else:
                chosen_x = float(raw_x if raw_x is not None else 0.5)
            x_ratio = max(0.0, min(1.0, chosen_x))
            crop_w = int(round(height * 9 / 16))
            crop_w = max(2, crop_w - (crop_w % 2))
            crop_w = min(width, crop_w)
            max_x = max(0, width - crop_w)
            x_off = int(round(max_x * x_ratio))
            vf = f"crop={crop_w}:{height}:{x_off}:0,scale=1080:1920,setsar=1,fps=30"
            return ["-vf", vf]

        # Default landscape handling: full frame centered on a blurred 9:16 background (never center-cropped)
        fc = (
            "split[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bgb];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30"
        )
        return ["-filter_complex", fc]

    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1,"
        "fps=30"
    )
    return ["-vf", vf]


def _ensure_music_meta(paths: AppPaths, row: dict[str, Any], abs_path: Path) -> dict[str, Any]:
    meta = loads_or(row.get("meta_json"), {})
    if not isinstance(meta, dict):
        meta = {}
    if "beat_times_s" not in meta or "energy_level" not in meta:
        try:
            beat_info = analyse_music_beats(abs_path, title_hint=str(meta.get("title") or abs_path.stem))
            meta.update(beat_info)
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE assets SET meta_json = ? WHERE id = ?",
                    (json.dumps(meta, ensure_ascii=False), int(row["id"])),
                )
        except Exception:
            pass
    return meta


def _score_music_match(meta: dict[str, Any], music_mood: str | None, energy_level: str | None) -> float:
    score = 0.0
    track_energy = str(meta.get("energy_level") or "moderate").lower()
    if energy_level:
        wanted_energy = energy_level.strip().lower()
        if track_energy == wanted_energy:
            score += 4.0
        elif "moderate" in (track_energy, wanted_energy):
            score += 1.5

    if music_mood:
        mood_lower = music_mood.lower()
        haystack = " ".join(
            [str(meta.get("title") or ""), *(str(t) for t in (meta.get("mood_tags") or []))]
        ).lower()
        tokens = [tok for tok in re.split(r"[,;/|\s]+", mood_lower) if len(tok) >= 3]
        for tok in tokens:
            if tok in haystack:
                score += 1.5
        if any(w in mood_lower for w in ("nhanh", "sôi động", "dồn dập", "upbeat", "fast", "beat")) and track_energy == "energetic":
            score += 3.0
        elif any(w in mood_lower for w in ("nhẹ", "ấm", "êm", "chậm", "calm", "soft", "piano")) and track_energy == "calm":
            score += 3.0
    return score


def pick_music_asset_record(
    paths: AppPaths,
    music_asset_id: int | None = None,
    *,
    music_mood: str | None = None,
    energy_level: str | None = None,
) -> dict[str, Any] | None:
    """Selects a music asset (explicit ID or best mood/energy match) and returns `{id, path, meta}`."""
    if music_asset_id is not None:
        row = query_one(
            paths.db_file,
            "SELECT id, path, meta_json FROM assets WHERE id = ? AND kind = 'music'",
            (music_asset_id,),
        )
        if row and row.get("path"):
            p = paths.media_dir / str(row["path"])
            if p.exists():
                meta = _ensure_music_meta(paths, row, p)
                return {"id": int(row["id"]), "path": p, "meta": meta}

    rows = query_all(paths.db_file, "SELECT id, path, meta_json FROM assets WHERE kind = 'music' ORDER BY id ASC")
    candidates: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        if not r.get("path"):
            continue
        p = paths.media_dir / str(r["path"])
        if not p.exists():
            continue
        meta = _ensure_music_meta(paths, r, p)
        match_score = _score_music_match(meta, music_mood, energy_level)
        candidates.append((match_score, {"id": int(r["id"]), "path": p, "meta": meta}))

    if not candidates:
        return None
    best_score = max(sc for sc, _ in candidates)
    top_tier = [rec for sc, rec in candidates if sc >= best_score - 0.25]
    return random.choice(top_tier)


def pick_music_asset(
    paths: AppPaths,
    music_asset_id: int | None = None,
    *,
    music_mood: str | None = None,
    energy_level: str | None = None,
) -> Path | None:
    rec = pick_music_asset_record(
        paths, music_asset_id=music_asset_id, music_mood=music_mood, energy_level=energy_level
    )
    return rec["path"] if rec is not None else None
