"""Decisions on a trend suggestion: accept (plan videos from it) or dismiss."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Literal

from videocreator.config import Settings, load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.paths import REPO_ROOT, AppPaths
from videocreator.pipeline.plan_request import save_plan_request_params
from videocreator.pipeline.render_inputs import pick_music_asset_record
from videocreator.studio.api_agent import can_start_studio_editor
from videocreator.studio.session import StudioBusyError, create_studio_session, enqueue_studio_job
from videocreator.trends.suggestion_formula import load_suggestion_formula

logger = logging.getLogger("videocreator.trends.suggest")


def _derive_voice_and_duration(
    cfg: Settings, trend_analysis: dict[str, Any]
) -> tuple[Literal["none", "vi", "en"], float]:
    ref_dur = 0.0
    try:
        ref_dur = float(trend_analysis.get("reference_duration_s") or 0.0)
    except (TypeError, ValueError):
        ref_dur = 0.0
    target_duration_s = round(max(5.0, min(60.0, ref_dur)), 1) if ref_dur >= 4.0 else 15.0

    audio_mode = str(trend_analysis.get("audio_mode") or "").strip().lower()
    if audio_mode in ("music_only", "asmr_original"):
        voice_lang: Literal["none", "vi", "en"] = "none"
    elif audio_mode == "voiceover":
        if cfg.telegram.default_voice_lang in ("vi", "en"):
            voice_lang = cfg.telegram.default_voice_lang
        elif (REPO_ROOT / "tools" / "MoneyPrinterTurbo").exists():
            voice_lang = cfg.telegram.default_caption_lang
        else:
            voice_lang = "none"
    else:
        voice_lang = cfg.telegram.default_voice_lang

    return voice_lang, target_duration_s


def _has_usable_shots(paths: AppPaths) -> bool:
    rows = query_all(
        paths.db_file,
        """
        SELECT COALESCE(f.path, a.path) AS rel_path
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE f.path IS NOT NULL OR a.path IS NOT NULL
        LIMIT 20
        """,
    )
    return any((paths.media_dir / str(r["rel_path"])).exists() for r in rows if r.get("rel_path"))


def _build_studio_trend_prompt(
    row: dict[str, Any],
    formula_obj: dict[str, Any],
    trend_analysis: dict[str, Any],
    target_duration_s: float,
) -> str:
    idea = str(row.get("text") or "").strip()
    formula_name = str(formula_obj.get("formula") or "trend-studio").strip()
    hook_layout = str(trend_analysis.get("hook_layout") or "big_center_title")
    cut_pace = trend_analysis.get("cut_pace_s")
    pace_note = f", nhịp cắt khoảng {cut_pace}s/cảnh" if cut_pace else ""
    return (
        f"Dựng video bám sát xu hướng (công thức `{formula_name}`, thời lượng khoảng {target_duration_s:.0f}s"
        f"{pace_note}, bố cục chữ `{hook_layout}`): {idea}"
    )


def accept_suggestion(
    paths: AppPaths,
    suggestion_id: int,
    *,
    count: int = 1,
    auto_render: bool = False,
    actor: str = "ui",
    render_mode: str | None = None,
) -> int | None:
    """Atomically accepts `suggestion_id` (`new`/`sent` -> `accepted`) and queues AI production.

    When `auto_render=True` and `count == 1` under `studio_preferred` / `studio_only`, launches a
    `studio` (Remotion) AI editing session with the Trend Blueprint + beat-synced music; seamlessly
    falls back to `plan` -> `render` (FFmpeg Enhanced) when Studio is busy or unavailable.
    """
    row = query_one(
        paths.db_file,
        "SELECT * FROM suggestions WHERE id = ?",
        (suggestion_id,),
    )
    if row is None:
        raise LookupError(f"Suggestion #{suggestion_id} not found")

    cfg = load_settings(paths.config_file)
    effective_mode = str(render_mode or cfg.trends.render_mode or "studio_preferred")
    formula_obj = load_suggestion_formula(paths.db_file, suggestion_id) or {}
    trend_analysis = (
        formula_obj.get("trend_analysis")
        if isinstance(formula_obj.get("trend_analysis"), dict)
        else {}
    )
    voice_lang, target_duration_s = _derive_voice_and_duration(cfg, trend_analysis)

    want_studio = auto_render and int(count) == 1 and effective_mode in ("studio_preferred", "studio_only")
    studio_ready = False
    if want_studio:
        shots_ok = _has_usable_shots(paths)
        ed_ok, ed_reason = can_start_studio_editor(paths, cfg)
        studio_ready = shots_ok and ed_ok
        if effective_mode == "studio_only" and not studio_ready:
            reason = ed_reason if shots_ok else "Kho shot đang trống; hãy nạp footage trước."
            raise RuntimeError(f"Chế độ Studio bắt buộc nhưng chưa sẵn sàng: {reason}")

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            UPDATE suggestions
            SET status = 'accepted'
            WHERE id = ? AND status IN ('new', 'sent')
            """,
            (suggestion_id,),
        )
        if cur.rowcount != 1:
            return None
        record_audit(
            conn,
            actor=actor,
            action="suggestion.accepted",
            object_type="suggestion",
            object_id=suggestion_id,
            detail=f"count={count}, auto_render={auto_render}, mode={'studio' if studio_ready else 'ffmpeg_enhanced'}",
        )

    if want_studio and studio_ready:
        music_rec = pick_music_asset_record(
            paths,
            music_mood=str(trend_analysis.get("music_mood") or ""),
            energy_level=str(trend_analysis.get("energy_level") or ""),
        )
        sfx_row = query_one(paths.db_file, "SELECT id FROM assets WHERE kind = 'sfx' ORDER BY id ASC LIMIT 1")
        formula_name = str(formula_obj.get("formula") or "trend-studio")
        initial_plan = {
            "title": str(row.get("text") or f"Trend #{suggestion_id}")[:60],
            "formula": formula_name,
            "shots": [],
            "trend_analysis": trend_analysis,
        }
        with get_conn(paths.db_file) as conn:
            v_cur = conn.execute(
                """
                INSERT INTO videos (engine, status, suggestion_id, voice_lang, caption_lang, auto_render, plan_json, captions_json)
                VALUES ('studio', 'planned', ?, ?, ?, 1, ?, '{}')
                """,
                (
                    suggestion_id,
                    voice_lang,
                    cfg.telegram.default_caption_lang,
                    json.dumps(initial_plan, ensure_ascii=False),
                ),
            )
            video_id = int(v_cur.lastrowid or 0)
        try:
            session_id = create_studio_session(
                paths,
                prompt=_build_studio_trend_prompt(row, formula_obj, trend_analysis, target_duration_s),
                ref_item_id=int(row["trend_item_id"]) if row.get("trend_item_id") is not None else None,
                video_id=video_id,
                options={
                    "auto_run": True,
                    "suggestion_id": suggestion_id,
                    "formula": formula_name,
                    "voice_lang": voice_lang,
                    "caption_lang": cfg.telegram.default_caption_lang,
                    "music_asset_id": int(music_rec["id"]) if music_rec else None,
                    "sfx_asset_id": int(sfx_row["id"]) if sfx_row else None,
                    "trend_blueprint": trend_analysis,
                    "beat_shot_map": formula_obj.get("beat_shot_map") or [],
                },
                actor=actor,
            )
            return enqueue_studio_job(paths.db_file, session_id)
        except StudioBusyError:
            with get_conn(paths.db_file) as conn:
                conn.execute("DELETE FROM videos WHERE id = ? AND status = 'planned'", (video_id,))
            if effective_mode == "studio_only":
                raise
            logger.info("Studio became busy; falling back to FFmpeg Enhanced for suggestion #%d", suggestion_id)

    # Use negative ref_id (-suggestion_id) so each suggestion's plan request file is isolated and uses library shots
    ref_key = -int(suggestion_id)
    save_plan_request_params(
        paths,
        ref_key,
        count=max(1, int(count)),
        voice_lang=voice_lang,
        caption_lang=cfg.telegram.default_caption_lang,
        target_duration_s=target_duration_s,
        formula=formula_obj,
        suggestion_id=suggestion_id,
        auto_render=auto_render,
    )
    job_id = enqueue_job(paths.db_file, "plan", ref_id=ref_key)
    return job_id


def dismiss_suggestion(
    db_file: Path,
    suggestion_id: int,
    *,
    actor: str = "ui",
) -> bool:
    """Atomically transitions `suggestion_id` from `new`/`sent` to `dismissed`."""
    row = query_one(db_file, "SELECT id FROM suggestions WHERE id = ?", (suggestion_id,))
    if row is None:
        raise LookupError(f"Suggestion #{suggestion_id} not found")

    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            UPDATE suggestions
            SET status = 'dismissed'
            WHERE id = ? AND status IN ('new', 'sent')
            """,
            (suggestion_id,),
        )
        if cur.rowcount != 1:
            return False
        record_audit(
            conn,
            actor=actor,
            action="suggestion.dismissed",
            object_type="suggestion",
            object_id=suggestion_id,
        )
        return True
