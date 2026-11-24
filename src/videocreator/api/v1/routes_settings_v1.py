"""Dashboard KPIs, Settings CRUD, masked Secrets management & AI Usage endpoints for `/api/v1`."""
from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from videocreator.ai.budget import budget_day, get_daily_api_spend
from videocreator.api.routes_settings import KNOWN_SECRET_KEYS
from videocreator.api.v1.deps import resolve_workspace_id
from videocreator.config import Settings, load_settings, save_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.job_store import get_queue_summary
from videocreator.jobs import JobWorker
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.workspaces import get_workspace

router = APIRouter()


class SecretsUpdateBody(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)
    delete_keys: list[str] = Field(default_factory=list)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


@router.get("/dashboard")
async def api_v1_dashboard(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    cfg = load_settings(paths.config_file)
    ws = get_workspace(paths.db_file, ws_id)

    def _cnt(sql: str, params: tuple[Any, ...]) -> int:
        r = query_one(paths.db_file, sql, params)
        return int(r["c"]) if r else 0

    vid_status_rows = query_all(
        paths.db_file,
        "SELECT status, COUNT(*) AS c FROM videos WHERE workspace_id = ? GROUP BY status",
        (ws_id,),
    )
    videos_by_status = {str(r["status"]): int(r["c"]) for r in vid_status_rows}

    counts = {
        "products": _cnt(
            "SELECT COUNT(*) AS c FROM products WHERE workspace_id = ? AND hidden = 0",
            (ws_id,),
        ),
        "footage": _cnt(
            "SELECT COUNT(*) AS c FROM footage WHERE workspace_id = ?", (ws_id,)
        ),
        "shots": _cnt(
            """
            SELECT COUNT(*) AS c FROM shots s
            LEFT JOIN footage f ON s.footage_id = f.id
            LEFT JOIN assets a ON s.asset_id = a.id
            WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
            """,
            (ws_id,),
        ),
        "trends": _cnt(
            "SELECT COUNT(*) AS c FROM trend_items WHERE workspace_id = ?", (ws_id,)
        ),
        "suggestions_new": _cnt(
            "SELECT COUNT(*) AS c FROM suggestions WHERE workspace_id = ? AND status IN ('new', 'sent')",
            (ws_id,),
        ),
        "videos_total": sum(videos_by_status.values()),
        "videos_by_status": videos_by_status,
        "accounts": _cnt(
            "SELECT COUNT(*) AS c FROM accounts WHERE workspace_id = ? AND enabled = 1",
            (ws_id,),
        ),
        "posts_scheduled": _cnt(
            """
            SELECT COUNT(*) AS c FROM posts p
            JOIN videos v ON p.video_id = v.id
            WHERE v.workspace_id = ? AND p.status = 'scheduled'
            """,
            (ws_id,),
        ),
        "posts_posted": _cnt(
            """
            SELECT COUNT(*) AS c FROM posts p
            JOIN videos v ON p.video_id = v.id
            WHERE v.workspace_id = ? AND p.status = 'posted'
            """,
            (ws_id,),
        ),
    }

    today = budget_day(paths.db_file)
    return JSONResponse(
        {
            "workspace_id": ws_id,
            "workspace": ws,
            "counts": counts,
            "queue": get_queue_summary(paths.db_file, workspace_id=ws_id),
            "ai_budget": {
                "day": today,
                "spent_usd": get_daily_api_spend(paths.db_file, bucket="daily", day=today),
                "limit_usd": cfg.budget.daily_usd,
            },
        }
    )


@router.get("/settings")
async def api_v1_get_settings(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    return JSONResponse(
        {"settings": cfg.model_dump(mode="json"), "data_dir": str(paths.data_dir)}
    )


@router.put("/settings")
async def api_v1_update_settings(
    request: Request, payload: dict[str, Any]
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cur = load_settings(paths.config_file).model_dump(mode="json")
    incoming = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
    merged = _deep_merge(cur, incoming)
    try:
        validated = Settings.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    try:
        ZoneInfo(validated.schedule.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid timezone: {validated.schedule.timezone}"
        ) from exc

    save_settings(paths.config_file, validated)
    worker: JobWorker | None = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.io_concurrency = int(validated.worker.io_concurrency)
        worker.compute_concurrency = int(validated.worker.compute_concurrency)

    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="api",
            action="settings.updated",
            object_type="config",
            detail=f"io={validated.worker.io_concurrency}, compute={validated.worker.compute_concurrency}",
        )
    return JSONResponse({"settings": validated.model_dump(mode="json")})


@router.get("/secrets")
async def api_v1_list_secrets(request: Request) -> JSONResponse:
    """Lists secret metadata (`configured: bool`) without EVER exposing secret values."""
    secrets: SecretsStore = request.app.state.secrets
    stored_keys = set(secrets.list_keys())
    known_names = {k for k, _ in KNOWN_SECRET_KEYS}
    items: list[dict[str, Any]] = []
    for key_name, label in KNOWN_SECRET_KEYS:
        items.append(
            {
                "name": key_name,
                "label": label,
                "configured": secrets.has(key_name),
            }
        )
    for extra in sorted(stored_keys - known_names):
        if extra.startswith("ACCOUNT_TOKEN_"):
            continue
        items.append(
            {
                "name": extra,
                "label": "Khóa tùy chỉnh",
                "configured": secrets.has(extra),
            }
        )
    return JSONResponse({"secrets": items})


@router.put("/secrets")
async def api_v1_update_secrets(
    request: Request, body: SecretsUpdateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    changed_keys: list[str] = []

    for raw_key, raw_val in body.secrets.items():
        clean_k = raw_key.strip()
        if not clean_k:
            continue
        clean_v = str(raw_val).strip()
        if clean_v:
            secrets.set(clean_k, clean_v)
            changed_keys.append(clean_k)

    deleted_keys: list[str] = []
    for raw_del in body.delete_keys:
        clean_d = raw_del.strip()
        if clean_d and secrets.has(clean_d):
            secrets.delete(clean_d)
            deleted_keys.append(clean_d)

    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="api",
            action="secrets.updated",
            object_type="secrets",
            detail=f"set={changed_keys}, deleted={deleted_keys}",
        )
    return JSONResponse(
        {
            "updated": changed_keys,
            "deleted": deleted_keys,
        }
    )


@router.get("/ai/usage")
async def api_v1_ai_usage(
    request: Request,
    days: int = Query(default=30, ge=1, le=90),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    today = budget_day(paths.db_file)
    rows = query_all(
        paths.db_file,
        """
        SELECT day, role, provider, model, route, kind,
               SUM(input_units) AS input_units,
               SUM(output_units) AS output_units,
               ROUND(SUM(cost_usd), 6) AS cost_usd,
               COUNT(*) AS calls
        FROM ai_usage
        GROUP BY day, role, provider, model, route, kind
        ORDER BY day DESC, cost_usd DESC
        LIMIT ?
        """,
        (days * 10,),
    )
    return JSONResponse(
        {
            "day": today,
            "daily_budget_usd": cfg.budget.daily_usd,
            "spent_today_usd": get_daily_api_spend(paths.db_file, bucket="daily", day=today),
            "generative_spent_today_usd": get_daily_api_spend(
                paths.db_file, bucket="generative", day=today
            ),
            "studio_spent_today_usd": get_daily_api_spend(
                paths.db_file, bucket="studio", day=today
            ),
            "entries": rows,
        }
    )
