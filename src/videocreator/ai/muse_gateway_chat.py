"""Subscription-backed `AIProvider` (`muse_gateway`) calling hardened Muse Gateway `/v1/chat/completions`."""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from videocreator.ai.base import (
    AIError,
    ProviderAuthError,
    ProviderQuotaExhausted,
    RouteKind,
    SchemaValidationError,
    T,
)
from videocreator.ai.budget import record_usage
from videocreator.config import load_settings
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import (
    MuseAuthError,
    MuseGatewayError,
    MuseQuotaWait,
)
from videocreator.secrets_store import SecretsStore

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json_text(raw: str) -> str:
    txt = (raw or "").strip()
    m = _FENCE_RE.search(txt)
    if m:
        return m.group(1).strip()
    first = txt.find("{")
    last = txt.rfind("}")
    if first != -1 and last > first:
        return txt[first : last + 1]
    return txt


class MuseGatewayChatProvider:
    """Implements `AIProvider` via local/remote hardened Muse Gateway (`route='subscription'`, `$0`)."""

    name: str = "muse_gateway"
    route_kind: RouteKind = "subscription"

    def __init__(
        self,
        db_file: Path,
        config_file: Path,
        secrets_store: SecretsStore,
        *,
        role: str = "writer",
        model: str = "muse-chat",
    ) -> None:
        self.db_file = db_file
        self.config_file = config_file
        self.secrets_store = secrets_store
        self.role = role
        self.model = model

    def describe_video(
        self,
        video: Path | str,
        prompt: str,
        schema: type[T],
        *,
        thumbnails: list[Path] | None = None,
    ) -> T:
        raise AIError("muse_gateway does not support direct video vision description")

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        settings = load_settings(self.config_file)
        cfg = settings.muse_gateway
        if not cfg.enabled:
            raise AIError("Muse Gateway is disabled in config.toml")

        try:
            client = MuseGatewayClient(cfg, self.secrets_store)
            client.verify_ready_and_safe()
        except MuseAuthError as exc:
            raise ProviderAuthError(self.name, str(exc)) from exc
        except MuseQuotaWait as exc:
            raise ProviderQuotaExhausted(self.name, str(exc), retry_after_s=exc.retry_after_s) from exc
        except MuseGatewayError as exc:
            raise AIError(str(exc)) from exc

        sys_instruction = (
            "Return ONLY a single valid JSON object matching this JSON schema, "
            f"with no markdown fences or commentary: {json.dumps(schema.model_json_schema())}"
        )

        last_val_err: Exception | None = None
        for attempt in range(2):
            try:
                data = client.chat_completion(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": sys_instruction},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )
            except MuseAuthError as exc:
                raise ProviderAuthError(self.name, str(exc)) from exc
            except MuseQuotaWait as exc:
                raise ProviderQuotaExhausted(
                    self.name, str(exc), retry_after_s=exc.retry_after_s
                ) from exc
            except MuseGatewayError as exc:
                raise AIError(str(exc)) from exc

            content = str(
                (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
            )
            record_usage(
                self.db_file,
                provider=self.name,
                model=self.model,
                kind=self.role,
                route="subscription",
                units_in=len(prompt),
                units_out=len(content),
                cost_usd=0.0,
            )
            try:
                return schema.model_validate_json(_extract_json_text(content))
            except ValidationError as val_exc:
                last_val_err = val_exc
                if attempt == 0:
                    continue
                raise SchemaValidationError(
                    f"muse_gateway output failed schema validation: {val_exc}"
                ) from val_exc

        raise SchemaValidationError(f"muse_gateway validation failed: {last_val_err}")


__all__ = ["MuseGatewayChatProvider"]
