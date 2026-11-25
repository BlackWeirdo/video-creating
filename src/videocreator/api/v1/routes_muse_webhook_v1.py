"""HMAC-signed webhook receiver for Muse Gateway task completion events (`/api/v1/integrations/muse/webhook`)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from videocreator.muse_gateway.webhook import (
    process_muse_webhook_event,
    verify_muse_webhook_signature,
)
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore

router = APIRouter()


@router.post("/integrations/muse/webhook")
async def api_v1_muse_webhook(request: Request) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    raw_body = await request.body()
    sig_header = request.headers.get("X-Muse-Signature")
    secret = (SecretsStore(paths.secrets_file).get("MUSE_GATEWAY_WEBHOOK_SECRET") or "").strip()

    if not verify_muse_webhook_signature(raw_body, sig_header, secret):
        raise HTTPException(status_code=401, detail="Invalid X-Muse-Signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    result = await asyncio.to_thread(process_muse_webhook_event, paths, payload)
    return JSONResponse(result)
