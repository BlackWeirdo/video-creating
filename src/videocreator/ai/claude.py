"""Anthropic Claude API adapter (`claude_api`) using the official `anthropic` SDK (Phase 04)."""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

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
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.thumbs import extract_thumbnail
from videocreator.secrets_store import SecretsStore


class ClaudeAPIProvider:
    """Implements `AIProvider` using `anthropic` SDK with structured output and budget guard."""

    name: str = "claude_api"
    route_kind: RouteKind = "api"

    def __init__(
        self,
        db_file: Path,
        config_file: Path,
        secrets_store: SecretsStore,
        *,
        role: str = "writer",
        model: str = "claude-sonnet-5-5",
    ) -> None:
        self.db_file = db_file
        self.config_file = config_file
        self.secrets_store = secrets_store
        self.role = role
        self.model = model

    def _get_client(self):  # type: ignore[no-untyped-def]
        api_key = self.secrets_store.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderAuthError(
                self.name,
                "ANTHROPIC_API_KEY is not configured in Settings / secrets.enc",
            )
        import anthropic

        return anthropic.Anthropic(api_key=api_key)

    def _call_messages(self, content_blocks: list[dict[str, Any]], schema: type[T]) -> T:
        settings = load_settings(self.config_file)
        check_budget(self.db_file, settings, kind=self.role)
        client = self._get_client()

        last_val_err: Exception | None = None
        for val_attempt in range(2):
            resp = None
            for net_attempt in range(3):
                try:
                    if hasattr(client.messages, "parse"):
                        resp = client.messages.parse(
                            model=self.model,
                            max_tokens=4096,
                            messages=[{"role": "user", "content": content_blocks}],
                            output_format=schema,
                        )
                    else:
                        resp = client.messages.create(
                            model=self.model,
                            max_tokens=4096,
                            messages=[{"role": "user", "content": content_blocks}],
                        )
                    break
                except Exception as exc:
                    msg = str(exc)
                    lower = msg.lower()
                    if "401" in lower or "403" in lower or "authentication" in lower:
                        raise ProviderAuthError(self.name, f"Claude API auth error: {msg}") from exc
                    if "429" in lower or "rate_limit" in lower or "overloaded" in lower:
                        if net_attempt < 2:
                            time.sleep(2 ** net_attempt)
                            continue
                        raise ProviderQuotaExhausted(
                            self.name, f"Claude API rate limit: {msg}", retry_after_s=1800
                        ) from exc
                    if any(code in lower for code in ("500", "502", "503", "529")) and net_attempt < 2:
                        time.sleep(2 ** net_attempt)
                        continue
                    raise AIError(f"Claude API call failed: {msg}") from exc

            if resp is None:
                raise AIError("Claude API returned no response")

            stop_reason = getattr(resp, "stop_reason", None)
            if stop_reason == "refusal":
                raise AIError("Claude API refused the request (stop_reason='refusal')")

            usage = getattr(resp, "usage", None)
            units_in = int(getattr(usage, "input_tokens", 0) or 0)
            units_out = int(getattr(usage, "output_tokens", 0) or 0)
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
                parsed = getattr(resp, "parsed_output", None)
                if isinstance(parsed, schema):
                    return parsed
                text_parts = [
                    getattr(b, "text", "")
                    for b in getattr(resp, "content", [])
                    if getattr(b, "type", "") == "text"
                ]
                raw_text = "\n".join(text_parts).strip()
                return schema.model_validate_json(raw_text)
            except ValidationError as val_exc:
                last_val_err = val_exc
                if val_attempt == 0:
                    check_budget(self.db_file, settings, kind=self.role)
                    continue
                raise SchemaValidationError(
                    f"Claude API output failed schema validation after 2 attempts: {val_exc}"
                ) from val_exc

        raise SchemaValidationError(f"Claude API validation failed: {last_val_err}")

    def describe_video(
        self,
        video: Path,
        prompt: str,
        schema: type[T],
        *,
        thumbnails: list[Path] | None = None,
    ) -> T:
        blocks: list[dict[str, Any]] = []
        thumb_paths = list(thumbnails or [])
        temp_thumb: Path | None = None
        try:
            if not thumb_paths and video.exists():
                info = probe_video(video)
                temp_thumb = video.parent / f".tmp_thumb_{video.stem}.jpg"
                extract_thumbnail(video, max(0.0, info.duration_s / 2.0), temp_thumb)
                thumb_paths = [temp_thumb]

            for idx, tpath in enumerate(thumb_paths, start=1):
                if not tpath.exists():
                    continue
                b64_data = base64.standard_b64encode(tpath.read_bytes()).decode("ascii")
                blocks.append(
                    {
                        "type": "text",
                        "text": f"Shot #{idx} ({tpath.name}):",
                    }
                )
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64_data,
                        },
                    }
                )
            blocks.append(
                {
                    "type": "text",
                    "text": f"{prompt}\nTrả về duy nhất 1 JSON object khớp schema: {schema.model_json_schema()}",
                }
            )
            return self._call_messages(blocks, schema)
        finally:
            if temp_thumb is not None:
                temp_thumb.unlink(missing_ok=True)

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        blocks = [
            {
                "type": "text",
                "text": f"{prompt}\nTrả về duy nhất 1 JSON object khớp schema: {schema.model_json_schema()}",
            }
        ]
        return self._call_messages(blocks, schema)
