"""HTTP Basic authentication on non-localhost and cross-origin CSRF protection (Phase 08, NFR-SEC-02)."""
from __future__ import annotations

import base64
import secrets
import threading
from pathlib import Path
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from videocreator.config import load_settings
from videocreator.secrets_store import SecretsStore

LOCALHOST_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
PUBLIC_HEALTH_PATHS: frozenset[str] = frozenset({"/health", "/api/v1/health"})
PROXIED_PREFIXES: tuple[str, ...] = (
    "/api/v1/",
    "/api/editor/",
    "/files/",
    "/assets/",
    "/freecut/",
)

_TRUSTED_UI_LOCK = threading.Lock()
_TRUSTED_UI_ORIGINS: set[str] = set()


def register_trusted_ui_origin(origin: str) -> str:
    norm = _normalize_origin(origin)
    if norm:
        with _TRUSTED_UI_LOCK:
            _TRUSTED_UI_ORIGINS.add(norm)
    return norm


def unregister_trusted_ui_origin(origin: str) -> None:
    norm = _normalize_origin(origin)
    if norm:
        with _TRUSTED_UI_LOCK:
            _TRUSTED_UI_ORIGINS.discard(norm)


def get_trusted_ui_origins() -> set[str]:
    with _TRUSTED_UI_LOCK:
        return set(_TRUSTED_UI_ORIGINS)


def _normalize_host_port(netloc: str, default_scheme: str) -> str:
    """Normalizes `host[:port]` with explicit default port so same-origin comparison is exact."""
    parsed = urlparse(f"{default_scheme}://{netloc}")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""
    port = parsed.port or (443 if default_scheme == "https" else 80)
    if ":" in hostname:
        return f"[{hostname}]:{port}"
    return f"{hostname}:{port}"


def _normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


def _is_cross_origin_mutation(
    request: Request, allowed_origins: set[str] | None = None
) -> tuple[bool, str]:
    """Blocks cross-origin state-changing browser requests (`POST`/`PUT`/`DELETE`/`PATCH`)
    using W3C Fetch Metadata (`Sec-Fetch-Site`) and `Origin` / `Referer` verification.
    Allows configured local frontend origins on `/api/v1/*` unless `Sec-Fetch-Site` is `cross-site`."""
    if request.method.upper() in SAFE_METHODS:
        return False, ""

    is_proxied_api = request.url.path.startswith(PROXIED_PREFIXES)
    allowed = allowed_origins or set()

    sec_fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if sec_fetch_site == "cross-site":
        return True, f"Cross-origin request blocked (Sec-Fetch-Site={sec_fetch_site})"

    req_scheme = request.url.scheme or "http"
    req_host_header = (request.headers.get("host") or request.url.netloc or "").strip()
    expected_authority = _normalize_host_port(req_host_header, req_scheme)

    origin = (request.headers.get("origin") or "").strip()
    normalized_origin = _normalize_origin(origin)
    origin_explicitly_allowed = (
        is_proxied_api and bool(normalized_origin) and (normalized_origin in allowed)
    )

    if sec_fetch_site and sec_fetch_site not in ("same-origin", "none"):
        if not (sec_fetch_site == "same-site" and origin_explicitly_allowed):
            return True, f"Cross-origin request blocked (Sec-Fetch-Site={sec_fetch_site})"

    if origin:
        if origin.lower() == "null":
            return True, "Cross-origin request blocked (Origin=null)"
        parsed_origin = urlparse(origin)
        origin_authority = _normalize_host_port(
            parsed_origin.netloc, parsed_origin.scheme or req_scheme
        )
        if not origin_authority or (
            origin_authority != expected_authority and not origin_explicitly_allowed
        ):
            return True, "Cross-origin request blocked (Origin mismatch)"
        return False, ""

    if not sec_fetch_site:
        referer = (request.headers.get("referer") or "").strip()
        if referer:
            parsed_ref = urlparse(referer)
            ref_authority = _normalize_host_port(
                parsed_ref.netloc, parsed_ref.scheme or req_scheme
            )
            ref_origin = _normalize_origin(f"{parsed_ref.scheme}://{parsed_ref.netloc}")
            ref_allowed = is_proxied_api and ref_origin in allowed
            if not ref_authority or (
                ref_authority != expected_authority and not ref_allowed
            ):
                return True, "Cross-origin request blocked (Referer mismatch)"

    return False, ""


class NonLocalhostBasicAuthMiddleware(BaseHTTPMiddleware):
    """Enforces cross-origin CSRF protection on all mutating routes and HTTP Basic Auth
    (`UI_PASSWORD`) whenever bound to a non-localhost interface."""

    def __init__(  # type: ignore[no-untyped-def]
        self,
        app,
        config_file: Path,
        secrets_store: SecretsStore,
        bind_host: str | None = None,
    ) -> None:
        super().__init__(app)
        self.config_file = config_file
        self.secrets_store = secrets_store
        self.bind_host = bind_host

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if request.url.path in PUBLIC_HEALTH_PATHS:
            return await call_next(request)

        settings = load_settings(self.config_file)
        allowed_origins = {
            _normalize_origin(o) for o in settings.web_ui.allowed_origins if o.strip()
        } | get_trusted_ui_origins()
        blocked, reason = _is_cross_origin_mutation(request, allowed_origins=allowed_origins)
        if blocked:
            return Response(content=reason, status_code=403)

        # The actual bind host (e.g. from --host) wins over config.toml.
        host = self.bind_host or settings.host
        if host.strip().lower() in LOCALHOST_HOSTS:
            return await call_next(request)

        expected_pw = self.secrets_store.get("UI_PASSWORD")
        if not expected_pw:
            return Response(
                content="UI_PASSWORD must be configured when binding outside localhost",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Video Creator"'},
            )

        auth_header = request.headers.get("Authorization") or ""
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                _, _, given_pw = decoded.partition(":")
                if secrets.compare_digest(given_pw, expected_pw):
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Video Creator"'},
        )
