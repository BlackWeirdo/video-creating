"""Subprocess execution, strict JSON schema conversion, and CLI error classification (Phase 18)."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from videocreator.ai.base import AIError, ProviderAuthError, ProviderQuotaExhausted

QUOTA_PATTERNS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "usage limit",
    "quota",
    "limit reached",
    "hit your limit",
    "5-hour limit",
    "resets at",
    "try again in",
    "too many requests",
    "overloaded",
)

AUTH_PATTERNS: tuple[str, ...] = (
    "not logged in",
    "please run claude login",
    "claude login",
    "authentication_error",
    "authentication failed",
    "invalid api key",
    "unauthorized",
    "oauth token",
    "please sign in",
    "login required",
)


def find_claude_binary() -> str | None:
    """Resolves `claude.exe` directly on Windows so npm `.cmd`/`.ps1` shims do not mangle `--json-schema`."""
    env_override = os.environ.get("CLAUDE_BINARY")
    if env_override and Path(env_override).exists():
        return env_override

    shim = shutil.which("claude")
    if shim:
        shim_path = Path(shim)
        direct_exe = shim_path.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if direct_exe.exists():
            return str(direct_exe)
        return str(shim_path)

    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = (
            Path(appdata)
            / "npm"
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
            / "bin"
            / "claude.exe"
        )
        if candidate.exists():
            return str(candidate)
    return None


def _parse_retry_after_seconds(text: str, default_s: int = 3600) -> int:
    """Extracts cooldown duration in seconds from CLI quota messages when present."""
    lower = text.lower()
    m_min = re.search(r"(\d+)\s*(?:minute|minutes|mins|min)\b", lower)
    if m_min:
        return max(60, int(m_min.group(1)) * 60)
    m_hr = re.search(r"(\d+)\s*(?:hour|hours|hr|hrs)\b", lower)
    if m_hr:
        return max(300, int(m_hr.group(1)) * 3600)
    m_sec = re.search(r"retry after\s*(\d+)\s*s", lower)
    if m_sec:
        return max(10, int(m_sec.group(1)))
    return default_s


def classify_cli_error(
    provider: str,
    stdout: str,
    stderr: str,
    *,
    api_error_status: int | None = None,
    result_text: str = "",
) -> AIError:
    """Classifies CLI failure output into `ProviderQuotaExhausted`, `ProviderAuthError`, or `AIError`."""
    combined = "\n".join(p for p in (result_text, stderr, stdout) if p).strip()
    lower = combined.lower()
    summary = (result_text or stderr or stdout or "Unknown CLI error").strip()[:400]

    if api_error_status == 429 or any(pat in lower for pat in QUOTA_PATTERNS):
        retry_s = _parse_retry_after_seconds(combined, default_s=3600)
        return ProviderQuotaExhausted(
            provider=provider,
            message=f"{provider} quota/rate limit reached: {summary}",
            retry_after_s=retry_s,
        )

    if api_error_status in (401, 403) or any(pat in lower for pat in AUTH_PATTERNS):
        return ProviderAuthError(
            provider=provider,
            message=f"{provider} authentication required: {summary}",
        )

    return AIError(f"{provider} CLI failed: {summary}")


def _enforce_no_additional_properties(node: Any) -> Any:
    if isinstance(node, dict):
        node.pop("title", None)
        node.pop("default", None)
        if node.get("type") == "object" or "properties" in node:
            node.setdefault("additionalProperties", False)
            if "properties" in node and isinstance(node["properties"], dict):
                node["required"] = list(node["properties"].keys())
        for k, v in list(node.items()):
            if k in ("properties", "$defs", "definitions") and isinstance(v, dict):
                node[k] = {
                    prop_name: _enforce_no_additional_properties(prop_schema)
                    for prop_name, prop_schema in v.items()
                }
            else:
                node[k] = _enforce_no_additional_properties(v)
    elif isinstance(node, list):
        return [_enforce_no_additional_properties(item) for item in node]
    return node


def pydantic_to_strict_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Converts a Pydantic `BaseModel` into a strict JSON Schema (`additionalProperties: false`)."""
    raw = schema.model_json_schema()
    return _enforce_no_additional_properties(raw)
