"""Meta Model API adapter (`muse_api`) for Muse Spark text/writer role (Phase 18)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from pydantic import ValidationError

from videocreator.ai.base import (
    AIError,
    ProviderAuthError,
    ProviderQuotaExhausted,
    RouteKind,
    SchemaValidationError,
    T,
)
from videocreator.ai.budget import check_budget, estimate_token_cost, record_usage
from videocreator.config import load_settings
from videocreator.secrets_store import SecretsStore


class MuseAPIProvider:
    """Implements `AIProvider` for Meta Model API (OpenAI-compatible chat completions endpoint)."""

    name: str = "muse_api"
    route_kind: RouteKind = "api"

    def __init__(
        self,
        db_file: Path,
        config_file: Path,
        secrets_store: SecretsStore,
        *,
        role: str = "writer",
        model: str = "Muse-Spark",
        base_url: str = "https://api.llama.com/compat/v1",
    ) -> None:
        self.db_file = db_file
        self.config_file = config_file
        self.secrets_store = secrets_store
        self.role = role
        self.model = model
        self.base_url = base_url.rstrip("/")

    def describe_video(
        self,
        video: Path,
        prompt: str,
        schema: type[T],
        *,
        thumbnails: list[Path] | None = None,
    ) -> T:
        raise AIError("muse_api does not support video vision description")

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        api_key = self.secrets_store.get("MUSE_API_KEY")
        if not api_key:
            raise ProviderAuthError(
                self.name,
                "MUSE_API_KEY is not configured in Settings / secrets.enc",
            )
        settings = load_settings(self.config_file)
        check_budget(self.db_file, settings, kind=self.role)

        for attempt in range(2):
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": f"Return strictly valid JSON matching schema: {json.dumps(schema.model_json_schema())}",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=90.0,
            )
            if resp.status_code in (401, 403):
                raise ProviderAuthError(self.name, f"Muse API auth failed ({resp.status_code})")
            if resp.status_code == 429:
                raise ProviderQuotaExhausted(
                    self.name, "Muse API rate limit (429)", retry_after_s=1800
                )
            if resp.status_code >= 400:
                raise AIError(f"Muse API HTTP {resp.status_code}: {resp.text[:300]}")

            data = resp.json()
            usage = data.get("usage") or {}
            units_in = int(usage.get("prompt_tokens") or 0)
            units_out = int(usage.get("completion_tokens") or 0)
            cost_usd = estimate_token_cost(settings, self.model, units_in, units_out)
            record_usage(
                self.db_file,
                provider=self.name,
                model=self.model,
                kind=self.role,
                route="api",
                units_in=units_in,
                units_out=units_out,
                cost_usd=cost_usd,
            )

            content = (
                ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
            )
            try:
                return schema.model_validate_json(content)
            except ValidationError as exc:
                if attempt == 0:
                    continue
                raise SchemaValidationError(f"Muse API invalid schema: {exc}") from exc

        raise SchemaValidationError("Muse API failed validation")
