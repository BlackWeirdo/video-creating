"""HTTP Basic authentication middleware when bound to a non-localhost interface (Phase 08, NFR-SEC-03)."""
from __future__ import annotations

import base64
import secrets
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from videocreator.config import load_settings
from videocreator.secrets_store import SecretsStore

LOCALHOST_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})


class NonLocalhostBasicAuthMiddleware(BaseHTTPMiddleware):
    """Requires HTTP Basic Auth (`UI_PASSWORD`) whenever `settings.host` is non-localhost."""

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
        if request.url.path == "/health":
            return await call_next(request)

        # The actual bind host (e.g. from --host) wins over config.toml.
        host = self.bind_host or load_settings(self.config_file).host
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
