"""Gemini API adapter (`gemini_api`) using the official `google-genai` SDK (Phase 04)."""
from __future__ import annotations

import time
from pathlib import Path

from pydantic import ValidationError

from videocreator.ai.base import AIError, ProviderAuthError, RouteKind, SchemaValidationError, T
from videocreator.ai.budget import check_budget, estimate_token_cost, record_usage
from videocreator.ai.retry import call_api_with_retry
from videocreator.config import load_settings
from videocreator.secrets_store import SecretsStore


class GeminiAPIProvider:
    """Implements `AIProvider` using `google-genai` with budget guard and structured JSON output."""

    name: str = "gemini_api"
    route_kind: RouteKind = "api"

    def __init__(
        self,
        db_file: Path,
        config_file: Path,
        secrets_store: SecretsStore,
        *,
        role: str = "vision",
        model: str = "gemini-2.5-flash",
    ) -> None:
        self.db_file = db_file
        self.config_file = config_file
        self.secrets_store = secrets_store
        self.role = role
        self.model = model

    def _get_client(self):  # type: ignore[no-untyped-def]
        api_key = self.secrets_store.get("GEMINI_API_KEY")
        if not api_key:
            raise ProviderAuthError(
                self.name,
                "GEMINI_API_KEY is not configured in Settings / secrets.enc",
            )
        from google import genai  # type: ignore[import-untyped]

        return genai.Client(api_key=api_key)

    def _call_with_retry(self, contents: list[object], schema: type[T]) -> T:
        from google.genai import types  # type: ignore[import-untyped]

        settings = load_settings(self.config_file)
        check_budget(self.db_file, settings, kind=self.role)
        client = self._get_client()

        last_val_err: Exception | None = None
        for val_attempt in range(2):
            resp = call_api_with_retry(
                lambda: client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                    ),
                ),
                provider=self.name,
                label="Gemini API",
                auth_markers=("401", "403", "api_key_invalid"),
                quota_markers=("429", "quota", "resource_exhausted"),
                quota_label="rate/quota limit",
                server_codes=("500", "502", "503", "504"),
            )
            if resp is None:
                raise AIError("Gemini API returned no response")

            usage_meta = getattr(resp, "usage_metadata", None)
            units_in = int(getattr(usage_meta, "prompt_token_count", 0) or 0)
            units_out = int(getattr(usage_meta, "candidates_token_count", 0) or 0)
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

            try:
                parsed = getattr(resp, "parsed", None)
                if isinstance(parsed, schema):
                    return parsed
                text_out = str(getattr(resp, "text", "") or "")
                return schema.model_validate_json(text_out)
            except ValidationError as val_exc:
                last_val_err = val_exc
                if val_attempt == 0:
                    check_budget(self.db_file, settings, kind=self.role)
                    continue
                raise SchemaValidationError(
                    f"Gemini API output failed schema validation after 2 attempts: {val_exc}"
                ) from val_exc

        raise SchemaValidationError(f"Gemini API validation failed: {last_val_err}")

    def describe_video(
        self,
        video: Path | str,
        prompt: str,
        schema: type[T],
        *,
        thumbnails: list[Path] | None = None,
    ) -> T:
        settings = load_settings(self.config_file)
        check_budget(self.db_file, settings, kind=self.role)
        video_str = str(video)
        if video_str.startswith(("http://", "https://")):
            from google.genai import types  # type: ignore[import-untyped]

            part = types.Part.from_uri(file_uri=video_str, mime_type="video/*")
            return self._call_with_retry([part, prompt], schema)

        client = self._get_client()
        uploaded = client.files.upload(file=video_str)
        try:
            for _ in range(90):
                state = getattr(uploaded, "state", None)
                state_name = getattr(state, "name", str(state or "")).upper()
                if "PROCESSING" not in state_name:
                    break
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
            return self._call_with_retry([uploaded, prompt], schema)
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        return self._call_with_retry([prompt], schema)
