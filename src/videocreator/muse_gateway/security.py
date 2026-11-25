"""Security guards for Muse Gateway: hardening assertion, prompt sanitization, SSRF & secret stripping."""
from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from videocreator.muse_gateway.errors import MuseInputError, MuseUnsafeGatewayError

_CWD_BLOCK_RE = re.compile(r"<cwd\b[^>]*>[\s\S]*?</cwd>", re.IGNORECASE)
_ENV_CTX_RE = re.compile(
    r"<environment_context\b[^>]*>[\s\S]*?</environment_context>", re.IGNORECASE
)
_CTRL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})


def sanitize_prompt(text: str) -> str:
    """Strips `<cwd>` / `<environment_context>` tags and control characters before sending to Muse."""
    cleaned = _ENV_CTX_RE.sub("", text or "")
    cleaned = _CWD_BLOCK_RE.sub("", cleaned)
    cleaned = _CTRL_CHARS_RE.sub("", cleaned)
    return cleaned.strip()


def _is_private_or_tailscale_host(hostname: str) -> bool:
    host = hostname.strip().lower().strip("[]")
    if host in LOOPBACK_HOSTS or host.endswith(".ts.net") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private:
        return True
    # Tailscale CGNAT 100.64.0.0/10
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.IPv4Network("100.64.0.0/10"):
        return True
    return False


def validate_gateway_base_url(base_url: str, mode: str = "local_sidecar") -> str:
    """Validates and normalizes Muse Gateway root URL (without `/v1` suffix)."""
    raw = (base_url or "").strip()
    if not raw:
        raise MuseInputError("Muse Gateway base_url cannot be empty")
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        raise MuseInputError(f"Invalid Muse Gateway URL: {raw}")

    host = parsed.hostname.lower()
    if mode == "local_sidecar":
        if host not in LOOPBACK_HOSTS:
            raise MuseUnsafeGatewayError(
                f"Chế độ local_sidecar chỉ cho phép kết nối loopback (127.0.0.1/localhost), nhận: {host}"
            )
    else:
        if scheme == "http" and not _is_private_or_tailscale_host(host):
            raise MuseUnsafeGatewayError(
                f"Gateway từ xa qua Internet bắt buộc dùng https:// (hoặc mạng riêng LAN/Tailscale), từ chối http://{host}"
            )

    clean_path = parsed.path.rstrip("/")
    if clean_path.endswith("/v1"):
        clean_path = clean_path[:-3]
    return urlunsplit((scheme, parsed.netloc, clean_path, "", "")).rstrip("/")


def assert_trusted_media_url(media_url: str, base_url: str) -> str:
    """Resolves `/api/media/<name>` against `base_url` and blocks cross-host SSRF redirects."""
    norm_base = validate_gateway_base_url(base_url, mode="remote")
    b = urlsplit(norm_base)
    raw = (media_url or "").strip()
    if not raw:
        raise MuseInputError("Empty Muse media URL")
    if raw.startswith("/"):
        if not raw.startswith("/api/media/"):
            raise MuseUnsafeGatewayError(f"Disallowed relative gateway path: {raw}")
        return f"{norm_base}{raw}"

    m = urlsplit(raw)
    if m.scheme.lower() != b.scheme.lower() or (m.hostname or "").lower() != (b.hostname or "").lower():
        raise MuseUnsafeGatewayError(
            f"Untrusted media host '{m.netloc}' does not match gateway '{b.netloc}'"
        )
    if (m.port or (443 if m.scheme == "https" else 80)) != (
        b.port or (443 if b.scheme == "https" else 80)
    ):
        raise MuseUnsafeGatewayError(
            f"Untrusted media port in '{raw}' does not match gateway '{norm_base}'"
        )
    if not m.path.startswith("/api/media/"):
        raise MuseUnsafeGatewayError(f"Disallowed gateway media path: {m.path}")
    return raw


def assert_hardened_config_payload(payload: dict[str, Any]) -> None:
    """Verifies `/api/config` reports `cmdMode == 'off'` and `hardened == True` (`vc-hardened` fork)."""
    cmd_mode = str(payload.get("cmdMode") or "").strip().lower()
    hardened = payload.get("hardened") is True
    if cmd_mode != "off" or not hardened:
        raise MuseUnsafeGatewayError(
            "Muse Gateway chưa được vá bảo mật (cmdMode != 'off' hoặc thiếu cờ hardened=true). "
            "Từ chối kết nối để ngăn rủi ro thực thi lệnh từ xa (RCE)."
        )


def _mask_email_or_name(val: str) -> str:
    s = (val or "").strip()
    if "@" not in s:
        return s
    local, _, domain = s.partition("@")
    if len(local) <= 2:
        return f"{local[:1]}***@{domain}"
    return f"{local[:2]}***@{domain}"


def _mask_proxy(proxy_url: str | None) -> str | None:
    if not proxy_url:
        return None
    raw = str(proxy_url).strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if not parsed.hostname:
        return "***"
    port_part = f":{parsed.port}" if parsed.port else ""
    auth_part = f"{parsed.username}:***@" if parsed.username else ""
    return f"{parsed.scheme or 'http'}://{auth_part}{parsed.hostname}{port_part}"


def strip_account_secrets(
    raw_session: dict[str, Any], pool_entry: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Removes cookies/tokens from a gateway session profile before returning to API/UI."""
    pe = pool_entry or {}
    acc_id = str(raw_session.get("id") or pe.get("id") or "")
    name = _mask_email_or_name(str(raw_session.get("name") or pe.get("name") or acc_id))
    return {
        "id": acc_id,
        "name": name,
        "enabled": bool(pe.get("enabled", True)),
        "status": str(pe.get("status") or "ready"),
        "cooldown_remaining_ms": int(pe.get("cooldownRemainingMs") or 0),
        "cooldown_reason": str(pe.get("cooldownReason") or ""),
        "lanes": pe.get("lanes") if isinstance(pe.get("lanes"), (int, list)) else pe.get("activeLanes", 0),
        "last_status": str(raw_session.get("lastStatus") or ""),
        "last_tested": raw_session.get("lastTested"),
        "proxy": _mask_proxy(raw_session.get("proxy")),
        "created_at": raw_session.get("createdAt"),
        "updated_at": raw_session.get("updatedAt"),
    }


__all__ = [
    "LOOPBACK_HOSTS",
    "assert_hardened_config_payload",
    "assert_trusted_media_url",
    "sanitize_prompt",
    "strip_account_secrets",
    "validate_gateway_base_url",
]
