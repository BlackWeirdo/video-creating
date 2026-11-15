"""Meta Graph API error classification, token inspection, and Page/IG discovery (Phase 07)."""
from __future__ import annotations
from typing import Any

import httpx

from videocreator.posting.base import PermanentPostError, TransientPostError

GRAPH_API_VERSION = "v22.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

RATE_LIMIT_CODES: frozenset[int] = frozenset({4, 17, 32, 613})
PERMANENT_AUTH_CODES: frozenset[int] = frozenset({10, 190, 200})


def classify_meta_error(status_code: int, payload: dict[str, Any] | str) -> Exception:
    """Maps Meta Graph API error responses to `TransientPostError` or `PermanentPostError`."""
    if isinstance(payload, dict):
        err = payload.get("error") or {}
        code = int(err.get("code") or 0)
        message = str(err.get("message") or payload)
        is_transient = bool(err.get("is_transient"))
    else:
        code = 0
        message = str(payload)
        is_transient = False

    if code in PERMANENT_AUTH_CODES or status_code in (401, 403):
        return PermanentPostError(f"Meta Graph auth/permission error (code={code}): {message}")
    if is_transient or code in RATE_LIMIT_CODES or status_code == 429 or status_code >= 500:
        return TransientPostError(f"Meta Graph transient error (HTTP {status_code}, code={code}): {message}")
    if status_code >= 400:
        return PermanentPostError(f"Meta Graph rejected request (HTTP {status_code}, code={code}): {message}")
    return TransientPostError(f"Unexpected Meta Graph error: {message}")


def list_pages_and_instagram(user_or_system_token: str) -> list[dict[str, Any]]:
    """Queries `/me/accounts` to discover Facebook Pages and linked Instagram Business accounts."""
    clean_token = user_or_system_token.strip()
    if not clean_token:
        raise ValueError("Meta access token is required")

    resp = httpx.get(
        f"{GRAPH_BASE_URL}/me/accounts",
        headers={"Authorization": f"Bearer {clean_token}"},
        params={
            "fields": "id,name,access_token,instagram_business_account{id,username,name}",
            "limit": "100",
        },
        timeout=30.0,
    )
    try:
        data = resp.json()
    except Exception:
        data = {}

    if resp.status_code >= 400:
        raise classify_meta_error(resp.status_code, data)

    discovered: list[dict[str, Any]] = []
    for page in data.get("data") or []:
        page_id = str(page.get("id") or "")
        page_name = str(page.get("name") or f"Page {page_id}")
        page_token = str(page.get("access_token") or clean_token)
        if page_id:
            discovered.append(
                {
                    "platform": "facebook",
                    "external_id": page_id,
                    "name": page_name,
                    "access_token": page_token,
                }
            )
        ig = page.get("instagram_business_account")
        if isinstance(ig, dict) and ig.get("id"):
            ig_id = str(ig["id"])
            ig_name = str(ig.get("username") or ig.get("name") or f"IG {ig_id}")
            discovered.append(
                {
                    "platform": "instagram",
                    "external_id": ig_id,
                    "name": f"@{ig_name} ({page_name})",
                    "access_token": page_token,
                }
            )
    return discovered
