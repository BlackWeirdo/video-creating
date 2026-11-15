"""Studio job: agent writes the script and the Remotion scene, the app checks, renders and exports (Phase 17).

Two stages, both run by the job worker (`studio` job, one session at a time):
  planning  -> agent writes `plan.json` (script); app checks it; stops at `awaiting_confirm` (`FR-STD-05`)
  rendering -> agent writes `src/Scene.tsx`; app scans, renders with Remotion, adds audio, exports

The agent (`claude -p` on the owner's subscription) can only read and write files inside the
session folder and read the vendored skill references: no shell, no web, no MCP (`FR-STD-10`).
"""
from __future__ import annotations
from typing import Any

from videocreator.ai.base import AIProvider, ProviderQuotaExhausted
from videocreator.ai.budget import check_budget
from videocreator.config import load_settings
from videocreator.db import get_conn, query_one, record_audit
from videocreator.engines.mpt_client import MPTClient
from videocreator.jobs import QuotaWaitRequested
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.studio.brief import build_brief
from videocreator.studio.claude_agent import CodeGenerator, StudioNotAvailableError, make_claude_generator
from videocreator.studio.export import export_studio_version, update_session
from videocreator.studio.remotion import ensure_workspace
from videocreator.studio.run import StudioRun
from videocreator.studio.session import session_options


def run_studio_job(
    paths: AppPaths,
    session_id: int,
    *,
    code_generator: CodeGenerator | None = None,
    mpt_client: MPTClient | None = None,
    checker_provider: AIProvider | None = None,
) -> dict[str, Any]:
    """Runs the pending stage(s) of a Studio session. Handler of the `studio` job.

    Any failure marks the session `failed` with the reason. Subscription quota exhaustion keeps the
    session where it is and parks the job (`waiting_quota`) so it continues by itself later.
    """
    try:
        return _run_stages(
            paths, session_id, code_generator=code_generator, mpt_client=mpt_client, checker_provider=checker_provider
        )
    except ProviderQuotaExhausted as exc:
        raise QuotaWaitRequested(str(exc), retry_after_s=int(getattr(exc, "retry_after_s", 3600) or 3600)) from exc
    except Exception as exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE studio_sessions SET status = 'failed', error = ? WHERE id = ?", (str(exc)[:600], session_id)
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
        generate = make_claude_generator(paths.db_file, settings)

    brief, footage_files = build_brief(paths, user_prompt, options)
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


def _run_stages(
    paths: AppPaths,
    session_id: int,
    *,
    code_generator: CodeGenerator | None,
    mpt_client: MPTClient | None,
    checker_provider: AIProvider | None,
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
            update_session(paths.db_file, session_id, status="awaiting_confirm", pending_prompt=None)
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
    )
    return {
        "session_id": session_id,
        "video_id": video_id,
        "status": "done",
        "version": version["version"],
        "session_ref": run.session_ref,
        "estimated_api_cost_usd": round(run.cost_usd, 4),
        "duration_s": duration_s,
    }
