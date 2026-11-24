"""Workspace-scoped Approvals, 5-Platform .zip Publish Packs, Channels, OAuth, Posts & Performance endpoints."""
from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from videocreator.api.v1.deps import resolve_workspace_id, serialize_v1_video
from videocreator.approvals import approve, bulk_approve, post_now, reject
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.posting.accounts import ACCOUNT_APPROVAL_MODES, upsert_account
from videocreator.posting.oauth import build_authorize_url
from videocreator.posting.performance import list_performance_rows
from videocreator.posting.post_actions import cancel_scheduled_post, retry_failed_post
from videocreator.posting.publish_pack import build_publish_pack_zip
from videocreator.posting.slots import account_slot_override, parse_slots_input
from videocreator.products import product_name_map
from videocreator.secrets_store import SecretsStore
from videocreator.state import InvalidTransitionError

router = APIRouter()


class ApproveBody(BaseModel):
    target_account_ids: list[int] | None = None
    auto_schedule: bool | None = None
    enforce_policy: bool = False


class RejectBody(BaseModel):
    reason: str = ""


class BulkApproveBody(BaseModel):
    video_ids: list[int]
    target_account_ids: list[int] | None = None
    enforce_policy: bool = True


class AccountCreateBody(BaseModel):
    workspace_id: int | None = None
    platform: Literal["facebook", "instagram", "threads", "tiktok", "youtube"]
    external_id: str
    name: str
    lang: Literal["vi", "en"] = "vi"
    access_token: str = ""
    slots: list[str] | None = None
    approval_mode: str = "inherit"
    autopilot_min_score: float = Field(default=8.0, ge=0.0, le=10.0)
    channel_group: str = ""


class AccountPatchBody(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    slots: list[str] | None = None
    approval_mode: str | None = None
    autopilot_min_score: float | None = Field(default=None, ge=0.0, le=10.0)
    channel_group: str | None = None


class OAuthAuthorizeBody(BaseModel):
    workspace_id: int | None = None
    lang: Literal["vi", "en"] = "vi"
    redirect_uri: str | None = None


# ---------- Approvals & .zip Publish Pack ----------


@router.get("/approvals")
async def api_v1_list_approvals(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    pmap = product_name_map(paths.db_file, workspace_id=ws_id)

    pending_rows = query_all(
        paths.db_file,
        "SELECT * FROM videos WHERE workspace_id = ? AND status = 'pending_approval' ORDER BY id DESC",
        (ws_id,),
    )
    recent_rows = query_all(
        paths.db_file,
        """
        SELECT * FROM videos
        WHERE workspace_id = ? AND status IN ('approved', 'rejected', 'scheduled', 'posted', 'partially_posted')
        ORDER BY id DESC LIMIT 20
        """,
        (ws_id,),
    )
    return JSONResponse(
        {
            "pending": [serialize_v1_video(r, product_map=pmap) for r in pending_rows],
            "recent": [serialize_v1_video(r, product_map=pmap) for r in recent_rows],
            "workspace_id": ws_id,
        }
    )


@router.post("/approvals/{video_id}/approve")
async def api_v1_approve_video(
    request: Request, video_id: int, body: ApproveBody | None = None
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        won = approve(
            paths.db_file,
            video_id,
            by="api",
            target_account_ids=body.target_account_ids if body else None,
            config_file=paths.config_file,
            auto_schedule=body.auto_schedule if body else None,
            enforce_policy=body.enforce_policy if body else False,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidTransitionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    ws_id = int((row or {}).get("workspace_id") or 1)
    return JSONResponse(
        {
            "won": won,
            "video": serialize_v1_video(
                row, product_map=product_name_map(paths.db_file, workspace_id=ws_id)
            )
            if row
            else None,
        }
    )


@router.post("/approvals/{video_id}/reject")
async def api_v1_reject_video(
    request: Request, video_id: int, body: RejectBody | None = None
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        won = reject(
            paths.db_file,
            video_id,
            by="api",
            reason=body.reason if body else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"won": won, "video_id": video_id})


@router.post("/approvals/bulk-approve")
async def api_v1_bulk_approve(
    request: Request, body: BulkApproveBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    result = bulk_approve(
        paths.db_file,
        body.video_ids,
        by="api",
        target_account_ids=body.target_account_ids,
        config_file=paths.config_file,
        enforce_policy=body.enforce_policy,
    )
    return JSONResponse(result)


@router.post("/approvals/{video_id}/post-now")
async def api_v1_post_now(request: Request, video_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        post_ids = post_now(paths.db_file, video_id, by="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidTransitionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"video_id": video_id, "post_ids": post_ids})


@router.get("/videos/{video_id}/publish-pack")
async def api_v1_download_publish_pack(
    request: Request,
    video_id: int,
    cover_title: str | None = Query(default=None),
) -> FileResponse:
    paths: AppPaths = request.app.state.paths
    try:
        zip_path = build_publish_pack_zip(paths, video_id, cover_title=cover_title)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"publish_pack_video_{video_id}.zip",
    )


# ---------- Channels / Accounts & OAuth ----------


def _serialize_account(row: dict[str, Any], secrets: SecretsStore) -> dict[str, Any]:
    secret_key = str(row.get("secret_key") or "")
    return {
        "id": int(row["id"]),
        "workspace_id": int(row.get("workspace_id") or 1),
        "platform": str(row.get("platform") or ""),
        "external_id": str(row.get("external_id") or ""),
        "name": str(row.get("name") or ""),
        "lang": str(row.get("lang") or "vi"),
        "slots": account_slot_override(row),
        "has_token": secrets.has(secret_key) if secret_key else False,
        "token_expires_at": row.get("token_expires_at"),
        "enabled": bool(row.get("enabled")),
        "approval_mode": str(row.get("approval_mode") or "inherit"),
        "autopilot_min_score": float(
            row.get("autopilot_min_score")
            if row.get("autopilot_min_score") is not None
            else 8.0
        ),
        "channel_group": str(row.get("channel_group") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


@router.get("/accounts")
async def api_v1_list_accounts(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    rows = query_all(
        paths.db_file,
        "SELECT * FROM accounts WHERE workspace_id = ? ORDER BY platform, id ASC",
        (ws_id,),
    )
    return JSONResponse(
        {
            "accounts": [_serialize_account(r, secrets) for r in rows],
            "workspace_id": ws_id,
        }
    )


@router.post("/accounts", status_code=201)
async def api_v1_create_account(
    request: Request, body: AccountCreateBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    ws_id = resolve_workspace_id(paths.db_file, body.workspace_id, require_active=True)
    try:
        acc_id = upsert_account(
            paths,
            platform=body.platform,
            external_id=body.external_id,
            name=body.name,
            access_token=body.access_token,
            lang=body.lang,
            workspace_id=ws_id,
            approval_mode=body.approval_mode,
            autopilot_min_score=body.autopilot_min_score,
            channel_group=body.channel_group,
            secrets_store=secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.slots is not None:
        try:
            normalized = parse_slots_input(",".join(body.slots))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE accounts SET slots_json = ? WHERE id = ?",
                (json.dumps(normalized) if normalized else None, acc_id),
            )
    row = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = ?", (acc_id,))
    assert row is not None
    return JSONResponse({"account": _serialize_account(row, secrets)}, status_code=201)


@router.patch("/accounts/{account_id}")
async def api_v1_patch_account(
    request: Request, account_id: int, body: AccountPatchBody
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    row = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = ?", (account_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Account #{account_id} not found")

    if body.approval_mode is not None and body.approval_mode not in ACCOUNT_APPROVAL_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid approval_mode '{body.approval_mode}'")

    next_slots = row.get("slots_json")
    if body.slots is not None:
        try:
            normalized = parse_slots_input(",".join(body.slots))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        next_slots = json.dumps(normalized) if normalized else None

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE accounts
            SET name = ?,
                enabled = ?,
                slots_json = ?,
                approval_mode = ?,
                autopilot_min_score = ?,
                channel_group = ?
            WHERE id = ?
            """,
            (
                body.name.strip() if body.name is not None else row["name"],
                (1 if body.enabled else 0) if body.enabled is not None else row["enabled"],
                next_slots,
                body.approval_mode or row["approval_mode"],
                body.autopilot_min_score
                if body.autopilot_min_score is not None
                else row["autopilot_min_score"],
                body.channel_group.strip()
                if body.channel_group is not None
                else (row.get("channel_group") or ""),
                account_id,
            ),
        )
        record_audit(
            conn,
            actor="api",
            action="account.updated",
            object_type="account",
            object_id=account_id,
        )
    updated = query_one(paths.db_file, "SELECT * FROM accounts WHERE id = ?", (account_id,))
    assert updated is not None
    return JSONResponse({"account": _serialize_account(updated, secrets)})


@router.delete("/accounts/{account_id}")
async def api_v1_delete_account(request: Request, account_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    row = query_one(paths.db_file, "SELECT secret_key FROM accounts WHERE id = ?", (account_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Account #{account_id} not found")
    sec_key = str(row["secret_key"])
    secrets.delete(sec_key)
    secrets.delete(f"{sec_key}_REFRESH")
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    return JSONResponse({"deleted": True, "account_id": account_id})


@router.post("/oauth/{platform}/authorize")
async def api_v1_oauth_authorize(
    request: Request, platform: str, body: OAuthAuthorizeBody | None = None
) -> JSONResponse:
    if platform not in ("threads", "tiktok", "youtube"):
        raise HTTPException(
            status_code=400,
            detail=f"Nền tảng OAuth không hỗ trợ: {platform} (chỉ threads, tiktok, youtube)",
        )
    paths: AppPaths = request.app.state.paths
    secrets: SecretsStore = request.app.state.secrets
    ws_id = resolve_workspace_id(
        paths.db_file, body.workspace_id if body else None, require_active=True
    )
    default_cb = str(request.base_url).rstrip("/") + f"/oauth/{platform}/callback"
    cb_uri = (body.redirect_uri if body and body.redirect_uri else default_cb).strip()
    try:
        auth_url, state = build_authorize_url(
            paths,
            platform,  # type: ignore[arg-type]
            redirect_uri=cb_uri,
            lang=body.lang if body else "vi",
            workspace_id=ws_id,
            secrets_store=secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"authorize_url": auth_url, "state": state, "platform": platform})


# ---------- Posts & Performance ----------


@router.get("/posts")
async def api_v1_list_posts(
    request: Request,
    workspace_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    sql = """
        SELECT p.*, a.platform, a.name AS account_name, a.lang, v.workspace_id
        FROM posts p
        JOIN accounts a ON p.account_id = a.id
        JOIN videos v ON p.video_id = v.id
        WHERE v.workspace_id = ?
    """
    params: list[Any] = [ws_id]
    if status and status.strip():
        sql += " AND p.status = ?"
        params.append(status.strip())
    sql += " ORDER BY p.scheduled_at DESC, p.id DESC LIMIT 200"
    rows = query_all(paths.db_file, sql, params)
    return JSONResponse({"posts": rows, "workspace_id": ws_id})


@router.post("/posts/{post_id}/retry")
async def api_v1_retry_post(request: Request, post_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        ok = retry_failed_post(paths.db_file, post_id, actor="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"retried": ok, "post_id": post_id})


@router.post("/posts/{post_id}/cancel")
async def api_v1_cancel_post(request: Request, post_id: int) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    try:
        ok = cancel_scheduled_post(paths.db_file, post_id, actor="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"cancelled": ok, "post_id": post_id})


@router.get("/performance")
async def api_v1_performance(
    request: Request,
    workspace_id: int | None = Query(default=None),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    ws_id = resolve_workspace_id(paths.db_file, workspace_id)
    vid_rows = query_all(
        paths.db_file, "SELECT id FROM videos WHERE workspace_id = ?", (ws_id,)
    )
    ws_video_ids = {int(r["id"]) for r in vid_rows}
    all_perf = list_performance_rows(paths.db_file)
    filtered = [item for item in all_perf if int(item["video_id"]) in ws_video_ids]
    return JSONResponse({"items": filtered, "workspace_id": ws_id})
