"""Studio job: agent writes the script and the Remotion scene, the app checks, renders and exports (Phase 17).

Two stages, both run by the job worker (`studio` job, one session at a time):
  planning  -> agent writes `plan.json` (script); app checks it; stops at `awaiting_confirm` (`FR-STD-05`)
  rendering -> agent writes `src/Scene.tsx`; app scans, renders with Remotion, adds audio, exports

The agent (`claude -p` on the owner's subscription) can only read and write files inside the
session folder and read the vendored skill references: no shell, no web, no MCP (`FR-STD-10`).
"""
from __future__ import annotations

import logging
import shutil
from typing import Any

from videocreator.ai.base import AIProvider, ProviderQuotaExhausted
from videocreator.ai.budget import check_budget
from videocreator.config import load_settings
from videocreator.db import get_conn, query_one, record_audit
from videocreator.engines.mpt_client import MPTClient
from videocreator.jobs import QuotaWaitRequested
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.quality_score import score_studio_video
from videocreator.studio.api_agent import make_studio_generator
from videocreator.studio.brief import build_brief
from videocreator.studio.claude_agent import CodeGenerator, StudioNotAvailableError
from videocreator.studio.export import export_studio_version, notify_studio_pending, update_session
from videocreator.studio.remotion import ensure_workspace
from videocreator.studio.run import StudioRun
from videocreator.studio.session import session_options

logger = logging.getLogger("videocreator.studio.agent")


def run_studio_job(
    paths: AppPaths,
    session_id: int,
    *,
    code_generator: CodeGenerator | None = None,
    mpt_client: MPTClient | None = None,
    checker_provider: AIProvider | None = None,
    vision_provider: AIProvider | None = None,
) -> dict[str, Any]:
    """Runs the pending stage(s) of a Studio session. Handler of the `studio` job.

    Any failure marks the session `failed` with the reason. Subscription quota exhaustion keeps the
    session where it is and parks the job (`waiting_quota`) so it continues by itself later.
    """
    try:
        return _run_stages(
            paths,
            session_id,
            code_generator=code_generator,
            mpt_client=mpt_client,
            checker_provider=checker_provider,
            vision_provider=vision_provider,
        )
    except QuotaWaitRequested:
        raise
    except ProviderQuotaExhausted as exc:
        raise QuotaWaitRequested(str(exc), retry_after_s=int(getattr(exc, "retry_after_s", 3600) or 3600)) from exc
    except Exception as exc:
        err_msg = str(exc)[:600]
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE studio_sessions SET status = 'failed', error = ? WHERE id = ?", (err_msg, session_id)
            )
            conn.execute(
                """
                UPDATE videos
                SET status = 'failed', error = ?
                WHERE id = (SELECT video_id FROM studio_sessions WHERE id = ?)
                  AND status = 'planned'
                """,
                (err_msg[:500], session_id),
            )
            record_audit(
                conn, actor="studio_agent", action="studio_session.failed",
                object_type="studio_session", object_id=session_id, detail=str(exc)[:300],
            )
        raise


def _prepare_run(
    paths: AppPaths,
    session: dict[str, Any],
    *,
    code_generator: CodeGenerator | None,
    mpt_client: MPTClient | None,
    checker_provider: AIProvider | None,
) -> StudioRun:
    """Checks budget and tooling, collects the brief, and scaffolds the session project."""
    settings = load_settings(paths.config_file)
    options = session_options(session)
    user_prompt = str(session["prompt"]).strip()

    check_budget(paths.db_file, settings, kind="studio", estimated_cost_usd=0.0)
    try:
        ensure_workspace()
    except RuntimeError as exc:
        raise StudioNotAvailableError(str(exc)) from exc
    generate: CodeGenerator | None = code_generator
    if generate is None and not options.get("template_id"):
        generate = make_studio_generator(paths, settings)

    ref_item_id = int(session["ref_item_id"]) if session.get("ref_item_id") is not None else None
    brief, footage_files = build_brief(paths, user_prompt, options, ref_item_id=ref_item_id)
    if not brief["shots"]:
        raise ValueError("Kho shot đang trống; hãy nạp và phân tích footage trước khi dùng Studio.")
    run = StudioRun(
        paths=paths,
        settings=settings,
        session_id=int(session["id"]),
        video_id=int(session["video_id"]),
        options=options,
        user_prompt=user_prompt,
        revision=str(session.get("pending_prompt") or "").strip() or None,
        brief=brief,
        footage_files=footage_files,
        generate=generate,
        mpt_client=mpt_client,
        checker_provider=checker_provider,
        session_ref=str(session.get("session_ref") or ""),
    )
    run.scaffold()
    return run


def _snapshot_video_state(paths: AppPaths, video_id: int, backup_dir: Any) -> dict[str, Any]:
    row = query_one(
        paths.db_file,
        "SELECT plan_json, captions_json, product_ids_json, duration_s, preflight_json, quality_score, quality_notes FROM videos WHERE id = ?",
        (video_id,),
    )
    master = paths.media_dir / f"output/video_{video_id}.mp4"
    cover = paths.media_dir / f"output/cover_{video_id}.jpg"
    bak_master = backup_dir / "v1.master.bak.mp4"
    bak_cover = backup_dir / "v1.cover.bak.jpg"
    if master.is_file():
        shutil.copy2(master, bak_master)
    if cover.is_file():
        shutil.copy2(cover, bak_cover)
    return {"row": row or {}, "bak_master": bak_master, "bak_cover": bak_cover}


def _restore_video_state(paths: AppPaths, video_id: int, snap: dict[str, Any]) -> None:
    master = paths.media_dir / f"output/video_{video_id}.mp4"
    cover = paths.media_dir / f"output/cover_{video_id}.jpg"
    if snap["bak_master"].is_file():
        shutil.copy2(snap["bak_master"], master)
    if snap["bak_cover"].is_file():
        shutil.copy2(snap["bak_cover"], cover)
    r = snap["row"]
    if r:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE videos
                SET status = 'pending_approval', plan_json = ?, captions_json = ?, product_ids_json = ?,
                    duration_s = ?, preflight_json = ?, quality_score = ?, quality_notes = ?, error = NULL
                WHERE id = ?
                """,
                (
                    r.get("plan_json"),
                    r.get("captions_json"),
                    r.get("product_ids_json"),
                    r.get("duration_s"),
                    r.get("preflight_json"),
                    r.get("quality_score"),
                    r.get("quality_notes"),
                    video_id,
                ),
            )


def _run_stages(
    paths: AppPaths,
    session_id: int,
    *,
    code_generator: CodeGenerator | None,
    mpt_client: MPTClient | None,
    checker_provider: AIProvider | None,
    vision_provider: AIProvider | None = None,
) -> dict[str, Any]:
    session = query_one(paths.db_file, "SELECT * FROM studio_sessions WHERE id = ?", (session_id,))
    if session is None:
        raise LookupError(f"Studio session #{session_id} not found")
    stage = str(session["status"])
    if stage not in ("planning", "rendering"):
        return {"session_id": session_id, "status": stage}
    versions = loads_or(session.get("versions_json"), [])

    run = _prepare_run(
        paths, session, code_generator=code_generator, mpt_client=mpt_client, checker_provider=checker_provider
    )
    video_id = run.video_id

    # Stage 1: script. A template session already has its plan.json and scene code.
    if stage == "planning":
        script, plan_json = run.write_script()
        # FR-STD-05: stop for the user's confirmation unless "run straight through" was chosen.
        # A revision of an already rendered session goes straight on: every version is kept anyway.
        if not run.options.get("auto_run") and not versions:
            new_cost = round(float(session.get("cost_usd") or 0.0) + run.cost_usd, 4)
            update_session(paths.db_file, session_id, status="awaiting_confirm", pending_prompt=None, cost_usd=new_cost)
            return {"session_id": session_id, "video_id": video_id, "status": "awaiting_confirm", "plan": plan_json}
        update_session(paths.db_file, session_id, status="rendering", pending_prompt=None)
    else:
        script = run.checked_script()
        if script.problems:
            raise ValueError(f"Kịch bản Studio không hợp lệ: {'; '.join(script.problems)[:500]}")
        if run.from_template:
            run.save_video_plan(script, [])  # shots and wording were chosen by the user, not written by AI

    # Stage 2: scene code -> BR-PRD-02 scan -> Remotion render.
    version_no = len(versions) + 1
    raw_out = run.session_dir / "out" / f"v{version_no}.mp4"
    run.render_scene(script, raw_out)

    should_auto_score = (
        not run.from_template
        and (bool(run.options.get("auto_run")) or bool(run.options.get("auto_score")) or vision_provider is not None)
    )

    version, duration_s = export_studio_version(
        paths,
        run.settings,
        session_id=session_id,
        video_id=video_id,
        session_dir=run.session_dir,
        version_no=version_no,
        raw_out=raw_out,
        scenes=script.scenes,
        clips=script.clips,
        voice_lang=run.voice_lang,
        options=run.options,
        version_prompt=run.revision or run.user_prompt,
        session_ref=run.session_ref or None,
        cost_usd=run.cost_usd,
        send_notification=not should_auto_score,
    )

    if should_auto_score:
        score1, _notes1, hint1 = score_studio_video(paths, video_id, provider=vision_provider)
        if (
            score1 is not None
            and score1 < run.settings.quality.min_score
            and version_no == 1
            and run.settings.quality.max_retries >= 1
            and run.generate is not None
        ):
            snap = _snapshot_video_state(paths, video_id, run.session_dir / "out")
            cost_before_rev = run.cost_usd
            try:
                update_session(paths.db_file, session_id, status="rendering")
                run.revision = (
                    f"Tự động tinh chỉnh sau chấm điểm chất lượng ({score1:.1f}/10 < {run.settings.quality.min_score:.1f}): "
                    f"{hint1}. Hãy sửa đúng điểm yếu này trong kịch bản hoặc trình bày chữ/nhịp cắt."
                )
                script2, _ = run.write_script()
                raw_out2 = run.session_dir / "out" / "v2.mp4"
                run.render_scene(script2, raw_out2)
                version2, duration2 = export_studio_version(
                    paths,
                    run.settings,
                    session_id=session_id,
                    video_id=video_id,
                    session_dir=run.session_dir,
                    version_no=2,
                    raw_out=raw_out2,
                    scenes=script2.scenes,
                    clips=script2.clips,
                    voice_lang=run.voice_lang,
                    options=run.options,
                    version_prompt=run.revision,
                    session_ref=run.session_ref or None,
                    cost_usd=max(0.0, round(run.cost_usd - cost_before_rev, 4)),
                    send_notification=False,
                )
                score2, _notes2, _ = score_studio_video(paths, video_id, provider=vision_provider)
                if score2 is not None and score2 >= score1:
                    version, duration_s = version2, duration2
                else:
                    _restore_video_state(paths, video_id, snap)
                    with get_conn(paths.db_file) as conn:
                        record_audit(
                            conn,
                            actor="auto_quality",
                            action="studio.best_version_kept",
                            object_type="video",
                            object_id=video_id,
                            detail=f"v1 ({score1:.1f}) kept over v2 ({score2})",
                        )
            except (QuotaWaitRequested, ProviderQuotaExhausted):
                _restore_video_state(paths, video_id, snap)
                update_session(paths.db_file, session_id, status="done")
            except Exception as rev_exc:
                logger.warning("Studio auto-revision failed on session #%d; keeping v1: %s", session_id, rev_exc)
                _restore_video_state(paths, video_id, snap)
                update_session(paths.db_file, session_id, status="done", error=None)
            finally:
                snap["bak_master"].unlink(missing_ok=True)
                snap["bak_cover"].unlink(missing_ok=True)

        notify_studio_pending(paths, video_id)

    return {
        "session_id": session_id,
        "video_id": video_id,
        "status": "done",
        "version": version["version"],
        "session_ref": run.session_ref,
        "estimated_api_cost_usd": round(run.cost_usd, 4),
        "duration_s": duration_s,
    }
