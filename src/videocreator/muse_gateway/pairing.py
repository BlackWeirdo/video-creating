"""One-click pairing with Muse Gateway (`/api/pair`) storing credentials in DPAPI SecretsStore."""
from __future__ import annotations

import secrets as _secrets
import threading
import time
from typing import Any

import httpx

from videocreator.config import load_settings
from videocreator.db import get_conn, record_audit
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import (
    MuseGatewayError,
    MuseInputError,
    MuseUnavailable,
)
from videocreator.muse_gateway.security import validate_gateway_base_url
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore

DEFAULT_ALLOWED_MUSE_MODELS: tuple[str, ...] = (
    "muse-video",
    "muse-image",
    "muse-voice",
    "muse-chat",
)

_PAIR_SESSIONS: dict[str, dict[str, Any]] = {}
_PAIR_LOCK = threading.Lock()


def _prune_pair_sessions() -> None:
    now = time.monotonic()
    expired = [pid for pid, rec in _PAIR_SESSIONS.items() if now - float(rec["ts"]) > 600.0]
    for pid in expired:
        _PAIR_SESSIONS.pop(pid, None)


def start_gateway_pairing(
    paths: AppPaths, *, app_name: str = "Video Creator V2"
) -> dict[str, Any]:
    """Starts `/api/pair` handshake on local Muse Gateway and returns `{pair_id, code, approve_url}`."""
    cfg = load_settings(paths.config_file).muse_gateway
    base_url = validate_gateway_base_url(cfg.base_url, cfg.mode)
    # Verify gateway is hardened BEFORE pairing!
    MuseGatewayClient(cfg).verify_ready_and_safe()

    try:
        resp = httpx.post(
            f"{base_url}/api/pair",
            json={"app": app_name},
            timeout=10.0,
            trust_env=False,
        )
    except httpx.RequestError as exc:
        raise MuseUnavailable(f"Không kết nối được Muse Gateway để ghép nối: {exc}") from exc

    if resp.status_code >= 400:
        raise MuseGatewayError(f"Ghép nối Muse Gateway thất bại ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    pair_id = str(data.get("id") or "").strip()
    pair_secret = str(data.get("secret") or "").strip()
    if not pair_id or not pair_secret:
        raise MuseGatewayError("Muse Gateway trả phản hồi ghép nối thiếu id/secret")

    with _PAIR_LOCK:
        _prune_pair_sessions()
        _PAIR_SESSIONS[pair_id] = {
            "secret": pair_secret,
            "base_url": base_url,
            "app_name": app_name,
            "code": str(data.get("code") or ""),
            "approve_url": str(data.get("approve_url") or f"{base_url}/pair/{pair_id}"),
            "ts": time.monotonic(),
        }

    return {
        "pair_id": pair_id,
        "code": str(data.get("code") or ""),
        "approve_url": str(data.get("approve_url") or f"{base_url}/pair/{pair_id}"),
        "expires_in": int(data.get("expires_in") or 300),
    }


def _restrict_paired_key_models(base_url: str, app_name: str) -> None:
    """Best-effort restriction of the paired API key to `muse-*` + existing combos via local `/api/keys`."""
    try:
        keys_resp = httpx.get(f"{base_url}/api/keys", timeout=8.0, trust_env=False)
        combos_resp = httpx.get(f"{base_url}/api/combos", timeout=8.0, trust_env=False)
        if keys_resp.status_code != 200:
            return
        keys_list = (keys_resp.json() or {}).get("keys") or []
        matching = [k for k in keys_list if isinstance(k, dict) and k.get("name") == app_name and k.get("enabled")]
        if not matching:
            return
        key_id = str(matching[-1].get("id") or "")
        if not key_id:
            return
        combo_names: list[str] = []
        if combos_resp.status_code == 200:
            for c in (combos_resp.json() or {}).get("combos") or []:
                if isinstance(c, dict) and c.get("name"):
                    combo_names.append(str(c["name"]))
        allowed = sorted({*DEFAULT_ALLOWED_MUSE_MODELS, *combo_names})
        httpx.patch(
            f"{base_url}/api/keys",
            json={"id": key_id, "access": {"restricted": True, "models": allowed}},
            timeout=8.0,
            trust_env=False,
        )
    except httpx.RequestError:
        pass


def poll_gateway_pairing(
    paths: AppPaths,
    pair_id: str,
    *,
    secrets_store: SecretsStore | None = None,
) -> dict[str, Any]:
    """Polls `/api/pair/{id}`; once approved, saves API key into `SecretsStore` without exposing it."""
    clean_id = (pair_id or "").strip()
    if not clean_id:
        raise MuseInputError("pair_id is required")

    with _PAIR_LOCK:
        _prune_pair_sessions()
        rec = _PAIR_SESSIONS.get(clean_id)

    if rec is None:
        raise MuseInputError("Phiên ghép nối không tồn tại hoặc đã hết hạn")

    base_url = str(rec["base_url"])
    try:
        resp = httpx.get(
            f"{base_url}/api/pair/{clean_id}",
            headers={"X-Pair-Secret": str(rec["secret"])},
            timeout=10.0,
            trust_env=False,
        )
    except httpx.RequestError as exc:
        raise MuseUnavailable(f"Lỗi kiểm tra trạng thái ghép nối: {exc}") from exc

    if resp.status_code == 404:
        raise MuseInputError("Phiên ghép nối đã hết hạn trên Muse Gateway")
    if resp.status_code >= 400:
        raise MuseGatewayError(f"Poll ghép nối lỗi ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    status = str(data.get("status") or "pending")
    raw_key = str(data.get("api_key") or "").strip()

    key_saved = False
    if raw_key:
        sec = secrets_store or SecretsStore(paths.secrets_file)
        sec.set("MUSE_GATEWAY_API_KEY", raw_key)
        if not sec.has("MUSE_GATEWAY_WEBHOOK_SECRET"):
            sec.set("MUSE_GATEWAY_WEBHOOK_SECRET", _secrets.token_hex(24))
        key_saved = True
        cfg = load_settings(paths.config_file).muse_gateway
        if cfg.mode == "local_sidecar":
            _restrict_paired_key_models(base_url, str(rec["app_name"]))
        with get_conn(paths.db_file) as conn:
            record_audit(
                conn,
                actor="muse_pairing",
                action="muse.paired",
                object_type="muse_gateway",
                detail=f"base_url={base_url}",
            )
        with _PAIR_LOCK:
            _PAIR_SESSIONS.pop(clean_id, None)

    return {
        "pair_id": clean_id,
        "status": "approved" if key_saved else status,
        "code": str(data.get("code") or rec["code"]),
        "approve_url": str(rec["approve_url"]),
        "key_saved": key_saved,
    }


__all__ = [
    "DEFAULT_ALLOWED_MUSE_MODELS",
    "poll_gateway_pairing",
    "start_gateway_pairing",
]
