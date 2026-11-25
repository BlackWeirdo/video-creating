"""Local-only admin proxy for Muse Gateway `/api/*` with cookie/secret stripping & settings whitelist."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from videocreator.config import load_settings
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import (
    MuseAuthError,
    MuseGatewayError,
    MuseInputError,
    MuseUnavailable,
)
from videocreator.muse_gateway.security import (
    strip_account_secrets,
    validate_gateway_base_url,
)
from videocreator.paths import AppPaths

ALLOWED_GATEWAY_SETTINGS_KEYS: frozenset[str] = frozenset(
    {
        "lanesMode",
        "lanesPerAccount",
        "autoHealEnabled",
        "keepAliveEnabled",
        "keepAliveMin",
        "maskEmails",
    }
)
FORBIDDEN_GATEWAY_SETTINGS_KEYS: frozenset[str] = frozenset(
    {
        "telegramEnabled",
        "telegramBotToken",
        "telegramChatId",
        "tunnelDashboardAccess",
        "dashboardToken",
    }
)
VALID_POOL_STRATEGIES: frozenset[str] = frozenset({"round-robin", "fallback", "fusion"})
VALID_USAGE_RANGES: frozenset[str] = frozenset({"today", "24h", "7d", "30d", "60d", "all"})


def _require_local_admin_base_url(paths: AppPaths) -> str:
    cfg = load_settings(paths.config_file).muse_gateway
    if cfg.mode != "local_sidecar":
        raise PermissionError(
            "Quản trị tài khoản/pool Muse Gateway chỉ khả dụng ở chế độ local_sidecar."
        )
    base_url = validate_gateway_base_url(cfg.base_url, "local_sidecar")
    MuseGatewayClient(cfg).verify_ready_and_safe()
    return base_url


def _extract_err(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except ValueError:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:300]


def _admin_request(
    paths: AppPaths,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout_s: float = 15.0,
) -> httpx.Response:
    base_url = _require_local_admin_base_url(paths)
    try:
        resp = httpx.request(
            method,
            f"{base_url}{path}",
            json=json_body,
            timeout=timeout_s,
            trust_env=False,
        )
    except httpx.RequestError as exc:
        raise MuseUnavailable(f"Không kết nối được Muse Gateway ({base_url}): {exc}") from exc

    if resp.status_code in (401, 403):
        raise MuseAuthError(f"Muse Gateway từ chối yêu cầu quản trị ({resp.status_code}): {_extract_err(resp)}")
    if resp.status_code == 404:
        raise LookupError(_extract_err(resp))
    if resp.status_code in (400, 409):
        raise MuseInputError(_extract_err(resp))
    if resp.status_code >= 500:
        raise MuseUnavailable(f"Muse Gateway lỗi máy chủ ({resp.status_code}): {_extract_err(resp)}")
    if resp.status_code >= 400:
        raise MuseGatewayError(f"Muse Gateway HTTP {resp.status_code}: {_extract_err(resp)}")
    return resp


def list_muse_accounts(paths: AppPaths) -> list[dict[str, Any]]:
    """Lists Muse accounts merging `/api/sessions` + `/api/pool` while stripping all cookies."""
    sess_resp = _admin_request(paths, "GET", "/api/sessions")
    pool_resp = _admin_request(paths, "GET", "/api/pool")
    sessions = sess_resp.json()
    pool_data = pool_resp.json()
    pool_accounts = pool_data.get("accounts") if isinstance(pool_data, dict) else []
    pool_by_id = {
        str(a.get("id")): a
        for a in (pool_accounts or [])
        if isinstance(a, dict) and a.get("id")
    }
    out: list[dict[str, Any]] = []
    if isinstance(sessions, list):
        for s in sessions:
            if isinstance(s, dict):
                out.append(strip_account_secrets(s, pool_by_id.get(str(s.get("id")))))
    return out


def import_muse_account_cookies(
    paths: AppPaths, *, name: str, cookies: str
) -> dict[str, Any]:
    clean_cookies = (cookies or "").strip()
    if not clean_cookies:
        raise MuseInputError("Chuỗi cookie đăng nhập Muse không được để trống")
    resp = _admin_request(
        paths,
        "POST",
        "/api/sessions",
        json_body={"name": (name or "").strip() or "Muse Account", "cookies": clean_cookies},
    )
    data = resp.json()
    raw_sess = (data.get("session") if isinstance(data, dict) else None) or {}
    return {
        "deduped": bool(data.get("deduped")) if isinstance(data, dict) else False,
        "account": strip_account_secrets(raw_sess if isinstance(raw_sess, dict) else {}),
    }


def start_muse_login_capture(
    paths: AppPaths,
    *,
    browser_type: str = "chrome",
    target_session_id: str | None = None,
) -> dict[str, Any]:
    b_type = browser_type if browser_type in ("chrome", "edge") else "chrome"
    body: dict[str, Any] = {"browserType": b_type}
    if target_session_id:
        body["targetSessionId"] = target_session_id
    resp = _admin_request(paths, "POST", "/api/login-capture", json_body=body, timeout_s=20.0)
    data = resp.json()
    return {"job_id": str(data.get("jobId") or ""), "status": "waiting"}


def poll_muse_login_capture(paths: AppPaths, job_id: str) -> dict[str, Any]:
    clean_id = (job_id or "").strip()
    if not clean_id:
        raise MuseInputError("job_id is required")
    qs = urlencode({"jobId": clean_id})
    resp = _admin_request(paths, "GET", f"/api/login-capture?{qs}")
    data = resp.json()
    return data if isinstance(data, dict) else {"status": "unknown"}


def cancel_muse_login_capture(paths: AppPaths, job_id: str) -> dict[str, Any]:
    clean_id = (job_id or "").strip()
    if not clean_id:
        raise MuseInputError("job_id is required")
    qs = urlencode({"jobId": clean_id})
    resp = _admin_request(paths, "DELETE", f"/api/login-capture?{qs}")
    data = resp.json()
    return {"cancelled": bool(data.get("success")) if isinstance(data, dict) else True}


def patch_muse_account(
    paths: AppPaths,
    account_id: str,
    *,
    name: str | None = None,
    proxy: str | None = None,
    enabled: bool | None = None,
    reset_cooldown: bool = False,
    close_lane: int | None = None,
) -> dict[str, Any]:
    clean_id = (account_id or "").strip()
    if not clean_id:
        raise MuseInputError("account_id is required")
    if name is not None and name.strip():
        _admin_request(paths, "PATCH", f"/api/sessions/{clean_id}", json_body={"name": name.strip()})
    if proxy is not None:
        _admin_request(
            paths,
            "PATCH",
            f"/api/sessions/{clean_id}",
            json_body={"proxy": proxy.strip() or None},
        )
    pool_patch: dict[str, Any] = {}
    if enabled is not None:
        pool_patch["enabled"] = bool(enabled)
    if reset_cooldown:
        pool_patch["resetCooldown"] = True
    if close_lane is not None:
        pool_patch["closeLane"] = int(close_lane)
    if pool_patch:
        pool_patch["accountId"] = clean_id
        _admin_request(paths, "PATCH", "/api/pool", json_body=pool_patch)

    accounts = list_muse_accounts(paths)
    found = next((a for a in accounts if a["id"] == clean_id), None)
    if found is None:
        raise LookupError(f"Account '{clean_id}' not found")
    return found


def delete_muse_account(paths: AppPaths, account_id: str) -> bool:
    clean_id = (account_id or "").strip()
    _admin_request(paths, "DELETE", f"/api/sessions/{clean_id}")
    return True


def test_muse_account(paths: AppPaths, account_id: str) -> dict[str, Any]:
    clean_id = (account_id or "").strip()
    resp = _admin_request(
        paths, "POST", "/api/sessions/test", json_body={"id": clean_id}, timeout_s=30.0
    )
    data = resp.json()
    return data if isinstance(data, dict) else {"id": clean_id, "valid": False}


def open_muse_account_browser(
    paths: AppPaths,
    account_id: str,
    *,
    url: str | None = None,
    browser_type: str = "chrome",
) -> dict[str, Any]:
    clean_id = (account_id or "").strip()
    body: dict[str, Any] = {
        "accountId": clean_id,
        "browserType": browser_type if browser_type in ("chrome", "edge") else "chrome",
    }
    if url:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in ("muse.ai", "www.muse.ai"):
            raise MuseInputError("Chỉ cho phép mở đường dẫn https://muse.ai/* trên trình duyệt tài khoản.")
        body["url"] = url.strip()
    resp = _admin_request(paths, "POST", "/api/launch-browser", json_body=body, timeout_s=25.0)
    data = resp.json()
    return data if isinstance(data, dict) else {"success": True}


def get_muse_pool(paths: AppPaths) -> dict[str, Any]:
    resp = _admin_request(paths, "GET", "/api/pool")
    data = resp.json()
    if not isinstance(data, dict):
        return {"strategy": "round-robin", "accounts": []}
    safe_accounts = [
        strip_account_secrets({"id": a.get("id"), "name": a.get("name")}, a)
        for a in (data.get("accounts") or [])
        if isinstance(a, dict)
    ]
    return {
        "strategy": str(data.get("strategy") or "round-robin"),
        "accounts": safe_accounts,
    }


def patch_muse_pool(paths: AppPaths, *, strategy: str) -> dict[str, Any]:
    clean = (strategy or "").strip()
    if clean not in VALID_POOL_STRATEGIES:
        raise MuseInputError(f"Chiến lược pool không hợp lệ: '{strategy}'")
    _admin_request(paths, "PATCH", "/api/pool", json_body={"strategy": clean})
    return get_muse_pool(paths)


def keepalive_muse_pool(paths: AppPaths) -> dict[str, Any]:
    resp = _admin_request(
        paths, "POST", "/api/pool", json_body={"action": "keepAliveAll"}, timeout_s=45.0
    )
    data = resp.json()
    return {
        "results": data.get("results") if isinstance(data, dict) else [],
        "pool": get_muse_pool(paths),
    }


def list_muse_combos(paths: AppPaths) -> list[dict[str, Any]]:
    resp = _admin_request(paths, "GET", "/api/combos")
    data = resp.json()
    combos = data.get("combos") if isinstance(data, dict) else []
    return [c for c in (combos or []) if isinstance(c, dict)]


def create_muse_combo(
    paths: AppPaths,
    *,
    name: str,
    account_ids: list[str],
    strategy: str = "round-robin",
    kind: str | None = None,
) -> dict[str, Any]:
    clean_name = (name or "").strip()
    if not clean_name:
        raise MuseInputError("Tên Combo không được để trống")
    strat = strategy if strategy in VALID_POOL_STRATEGIES else "round-robin"
    body: dict[str, Any] = {
        "name": clean_name,
        "accountIds": [str(a) for a in account_ids if str(a).strip()],
        "strategy": strat,
    }
    if kind in ("chat", "image", "video", "audio"):
        body["kind"] = kind
    resp = _admin_request(paths, "POST", "/api/combos", json_body=body)
    data = resp.json()
    return data if isinstance(data, dict) else {}


def patch_muse_combo(paths: AppPaths, combo_id: str, patch: dict[str, Any]) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"id": (combo_id or "").strip()}
    if "name" in patch and patch["name"] is not None:
        body["name"] = str(patch["name"]).strip()
    if "account_ids" in patch and isinstance(patch["account_ids"], list):
        body["accountIds"] = [str(a) for a in patch["account_ids"]]
    elif "accountIds" in patch and isinstance(patch["accountIds"], list):
        body["accountIds"] = [str(a) for a in patch["accountIds"]]
    if patch.get("strategy") in VALID_POOL_STRATEGIES:
        body["strategy"] = patch["strategy"]
    if patch.get("kind") in ("chat", "image", "video", "audio"):
        body["kind"] = patch["kind"]
    resp = _admin_request(paths, "PATCH", "/api/combos", json_body=body)
    data = resp.json()
    return list((data or {}).get("combos") or []) if isinstance(data, dict) else []


def delete_muse_combo(paths: AppPaths, combo_id: str) -> list[dict[str, Any]]:
    qs = urlencode({"id": (combo_id or "").strip()})
    resp = _admin_request(paths, "DELETE", f"/api/combos?{qs}")
    data = resp.json()
    return list((data or {}).get("combos") or []) if isinstance(data, dict) else []


def _filter_gateway_settings_view(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: raw[k] for k in ALLOWED_GATEWAY_SETTINGS_KEYS if k in raw}


def get_muse_gateway_settings(paths: AppPaths) -> dict[str, Any]:
    resp = _admin_request(paths, "GET", "/api/settings")
    data = resp.json()
    return _filter_gateway_settings_view(data if isinstance(data, dict) else {})


def patch_muse_gateway_settings(paths: AppPaths, patch: dict[str, Any]) -> dict[str, Any]:
    forbidden = sorted(FORBIDDEN_GATEWAY_SETTINGS_KEYS.intersection(patch.keys()))
    if forbidden:
        raise MuseInputError(f"Không cho phép chỉnh sửa trường nhạy cảm trên gateway: {', '.join(forbidden)}")
    filtered = {k: v for k, v in patch.items() if k in ALLOWED_GATEWAY_SETTINGS_KEYS and v is not None}
    if not filtered:
        return get_muse_gateway_settings(paths)
    resp = _admin_request(paths, "PATCH", "/api/settings", json_body=filtered)
    data = resp.json()
    return _filter_gateway_settings_view(data if isinstance(data, dict) else {})


def list_muse_gateway_keys(paths: AppPaths) -> dict[str, Any]:
    """Lists gateway API keys in masked form ONLY (`?reveal=` is strictly prohibited)."""
    resp = _admin_request(paths, "GET", "/api/keys")
    data = resp.json()
    if not isinstance(data, dict):
        return {"keys": [], "authRequired": False, "requireAuth": False}
    safe_keys: list[dict[str, Any]] = []
    for k in data.get("keys") or []:
        if not isinstance(k, dict):
            continue
        entry = dict(k)
        raw_k = str(entry.get("key") or "")
        if "…" not in raw_k and "..." not in raw_k and len(raw_k) > 12:
            entry["key"] = f"{raw_k[:8]}…{raw_k[-4:]}"
        safe_keys.append(entry)
    return {
        "keys": safe_keys,
        "authRequired": bool(data.get("authRequired")),
        "requireAuth": bool(data.get("requireAuth")),
    }


def patch_muse_gateway_key(
    paths: AppPaths,
    key_id: str,
    *,
    enabled: bool | None = None,
    access: dict[str, Any] | None = None,
    require_auth: bool | None = None,
) -> dict[str, Any]:
    if require_auth is not None:
        resp = _admin_request(paths, "PATCH", "/api/keys", json_body={"requireAuth": bool(require_auth)})
        return resp.json() if isinstance(resp.json(), dict) else {"ok": True}
    clean_id = (key_id or "").strip()
    if access is not None:
        resp = _admin_request(paths, "PATCH", "/api/keys", json_body={"id": clean_id, "access": access})
        return resp.json() if isinstance(resp.json(), dict) else {"ok": True}
    if enabled is not None:
        resp = _admin_request(paths, "PATCH", "/api/keys", json_body={"id": clean_id, "enabled": bool(enabled)})
        return resp.json() if isinstance(resp.json(), dict) else {"ok": True}
    return {"ok": True}


def get_muse_gateway_usage(paths: AppPaths, range_key: str = "today") -> dict[str, Any]:
    rk = range_key if range_key in VALID_USAGE_RANGES else "today"
    resp = _admin_request(paths, "GET", f"/api/usage?{urlencode({'range': rk})}")
    data = resp.json()
    return data if isinstance(data, dict) else {"range": rk, "totals": {}}


def get_muse_gateway_usage_csv(paths: AppPaths, range_key: str = "today") -> str:
    rk = range_key if range_key in VALID_USAGE_RANGES else "today"
    resp = _admin_request(paths, "GET", f"/api/usage?{urlencode({'range': rk, 'format': 'csv'})}")
    return resp.text


def get_muse_gateway_overview(paths: AppPaths) -> dict[str, Any]:
    try:
        resp = _admin_request(paths, "GET", "/api/overview")
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except LookupError:
        return {}


def cleanup_muse_gateway_tasks(paths: AppPaths, scope: str = "failed") -> dict[str, Any]:
    if scope not in ("failed", "finished"):
        raise MuseInputError("scope phải là 'failed' hoặc 'finished'")
    resp = _admin_request(paths, "DELETE", f"/api/tasks?{urlencode({'scope': scope})}")
    data = resp.json()
    return data if isinstance(data, dict) else {"removed": 0}


def check_muse_gateway_update(paths: AppPaths) -> dict[str, Any]:
    """Read-only update check (`GET /api/update` ONLY; auto-install `POST` is prohibited)."""
    resp = _admin_request(paths, "GET", "/api/update", timeout_s=12.0)
    data = resp.json()
    return data if isinstance(data, dict) else {}


def export_muse_gateway_backup(paths: AppPaths) -> dict[str, Any]:
    """Internal helper for encrypted `.vcx` bundle ONLY (contains cookies/keys!)."""
    resp = _admin_request(paths, "GET", "/api/backup", timeout_s=20.0)
    data = resp.json()
    return data if isinstance(data, dict) else {}


def restore_muse_gateway_backup(paths: AppPaths, payload: dict[str, Any]) -> dict[str, Any]:
    """Internal helper restoring gateway state from a decrypted `.vcx` bundle."""
    resp = _admin_request(paths, "POST", "/api/backup", json_body=payload, timeout_s=20.0)
    data = resp.json()
    return data if isinstance(data, dict) else {"success": False}


__all__ = [
    "ALLOWED_GATEWAY_SETTINGS_KEYS",
    "cancel_muse_login_capture",
    "check_muse_gateway_update",
    "cleanup_muse_gateway_tasks",
    "create_muse_combo",
    "delete_muse_account",
    "delete_muse_combo",
    "export_muse_gateway_backup",
    "get_muse_gateway_overview",
    "get_muse_gateway_settings",
    "get_muse_gateway_usage",
    "get_muse_gateway_usage_csv",
    "get_muse_pool",
    "import_muse_account_cookies",
    "keepalive_muse_pool",
    "list_muse_accounts",
    "list_muse_combos",
    "list_muse_gateway_keys",
    "open_muse_account_browser",
    "patch_muse_account",
    "patch_muse_combo",
    "patch_muse_gateway_key",
    "patch_muse_gateway_settings",
    "patch_muse_pool",
    "poll_muse_login_capture",
    "restore_muse_gateway_backup",
    "start_muse_login_capture",
    "test_muse_account",
]
