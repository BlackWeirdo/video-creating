"""Channel Autopilot CRUD & trigger endpoints for `/api/v1`."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.autopilot import (
    create_autopilot_rule,
    delete_autopilot_rule,
    get_autopilot_rule,
    list_autopilot_rules,
    list_autopilot_runs,
    run_autopilot_tick,
    update_autopilot_rule,
)
from videocreator.jobs import enqueue_job
from videocreator.paths import AppPaths

router = APIRouter()


class AutopilotRuleCreateBody(BaseModel):
    workspace_id: int | None = None
    name: str
    source_mode: str = "rss_feed"
    feed_url: str = ""
    target_account_ids: list[int] = Field(default_factory=list)
    daily_cap: int = 3
    min_quality_score: float = 8.0
    style_preset: str = "tiktok_karaoke"
    aspect_ratio: str = "9:16"
    interval_minutes: int = 60
    enabled: bool = True


class AutopilotRulePatchBody(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    feed_url: str | None = None
    target_account_ids: list[int] | None = None
    daily_cap: int | None = None
    min_quality_score: float | None = None
    style_preset: str | None = None
    aspect_ratio: str | None = None
    interval_minutes: int | None = None


class AutopilotTriggerBody(BaseModel):
    sync: bool = False
    force: bool = True
    score_override: float | None = None


@router.get("/autopilot/rules")
async def api_v1_list_autopilot_rules(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    return JSONResponse(
        {
            "rules": list_autopilot_rules(paths.db_file, workspace_id=ws_id),
            "workspace_id": ws_id,
        }
    )


@router.post("/autopilot/rules", status_code=201)
async def api_v1_create_autopilot_rule(
    request: Request, body: AutopilotRuleCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id)
    try:
        rule = create_autopilot_rule(
            paths,
            workspace_id=ws_id,
            name=body.name,
            source_mode=body.source_mode,
            feed_url=body.feed_url,
            target_account_ids=body.target_account_ids,
            daily_cap=body.daily_cap,
            min_quality_score=body.min_quality_score,
            style_preset=body.style_preset,
            aspect_ratio=body.aspect_ratio,
            interval_minutes=body.interval_minutes,
            enabled=body.enabled,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"rule": rule}, status_code=201)


@router.patch("/autopilot/rules/{rule_id}")
async def api_v1_patch_autopilot_rule(
    request: Request, rule_id: int, body: AutopilotRulePatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        rule = update_autopilot_rule(
            paths,
            rule_id,
            name=body.name,
            enabled=body.enabled,
            feed_url=body.feed_url,
            target_account_ids=body.target_account_ids,
            daily_cap=body.daily_cap,
            min_quality_score=body.min_quality_score,
            style_preset=body.style_preset,
            aspect_ratio=body.aspect_ratio,
            interval_minutes=body.interval_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Autopilot rule #{rule_id} not found")
    return JSONResponse({"rule": rule})


@router.delete("/autopilot/rules/{rule_id}")
async def api_v1_delete_autopilot_rule(request: Request, rule_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    if not delete_autopilot_rule(paths, rule_id):
        raise HTTPException(status_code=404, detail=f"Autopilot rule #{rule_id} not found")
    return JSONResponse({"ok": True, "deleted_id": rule_id})


@router.post("/autopilot/rules/{rule_id}/trigger")
async def api_v1_trigger_autopilot_rule(
    request: Request,
    rule_id: int,
    body: AutopilotTriggerBody | None = None,
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    rule = get_autopilot_rule(paths.db_file, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Autopilot rule #{rule_id} not found")
    payload = body or AutopilotTriggerBody()
    if payload.sync:
        results = run_autopilot_tick(
            paths,
            rule_id=rule_id,
            force=payload.force,
            score_override=payload.score_override,
        )
        return JSONResponse({"results": results, "job_id": None})

    job_id = enqueue_job(
        paths.db_file,
        "autopilot_tick",
        ref_id=rule_id,
        lane="io",
        workspace_id=int(rule["workspace_id"]),
    )
    return JSONResponse({"results": [], "job_id": job_id}, status_code=202)


@router.get("/autopilot/runs")
async def api_v1_list_autopilot_runs(
    request: Request,
    workspace_id: int | None = Query(default=None),
    rule_id: int | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=300),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id) if workspace_id is not None else None
    runs = list_autopilot_runs(
        paths.db_file,
        workspace_id=ws_id,
        rule_id=rule_id,
        limit=limit,
    )
    return JSONResponse({"runs": runs})
