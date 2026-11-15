"""Registers the handler of every job kind with the job registry."""
from __future__ import annotations

from videocreator.jobs import JobRegistry
from videocreator.paths import AppPaths
from videocreator.pipeline.broll_suggest import BROLL_SUGGEST_JOB_KIND, run_broll_suggest_job
from videocreator.pipeline.describe import run_describe_footage
from videocreator.pipeline.footage_analyse import run_analyse_footage
from videocreator.pipeline.plan_request import run_plan_footage
from videocreator.pipeline.render import render_video
from videocreator.pipeline.replan import replan_video
from videocreator.studio.agent import run_studio_job
from videocreator.studio.session import STUDIO_JOB_KIND
from videocreator.trends.analyse_queue import ANALYSE_TREND_JOB_KIND
from videocreator.trends.links import run_analyse_trend_job
from videocreator.trends.scan_job import run_scan_and_suggest_job


def register_job_handlers(job_registry: JobRegistry, paths: AppPaths) -> None:
    job_registry.register(
        "analyse",
        lambda ref_id: run_analyse_footage(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "describe",
        lambda ref_id: run_describe_footage(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "plan",
        lambda ref_id: run_plan_footage(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "replan",
        lambda ref_id: replan_video(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "render",
        lambda ref_id: render_video(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "scan_trends",
        lambda ref_id: run_scan_and_suggest_job(paths, int(ref_id or 0)),
    )
    job_registry.register(
        "trend_scan",
        lambda ref_id: run_scan_and_suggest_job(paths, int(ref_id or 0)),
    )
    job_registry.register(
        STUDIO_JOB_KIND,
        lambda ref_id: str(run_studio_job(paths, int(ref_id or 0)).get("status")),
    )
    job_registry.register(
        BROLL_SUGGEST_JOB_KIND,
        lambda _ref_id: run_broll_suggest_job(paths),
    )
    job_registry.register(
        ANALYSE_TREND_JOB_KIND,
        lambda ref_id: run_analyse_trend_job(paths, int(ref_id or 0)),
    )
