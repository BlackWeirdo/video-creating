"""Tests for CLI error classification on real error payloads and strict JSON schema generation (Phase 18)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from videocreator.ai.base import ProviderAuthError, ProviderQuotaExhausted
from videocreator.ai.cli_base import classify_cli_error, pydantic_to_strict_json_schema
from videocreator.pipeline.describe import ShotDescriptionsResponse

SAMPLES_ERR_DIR = Path(__file__).resolve().parent / "samples" / "cli_errors"


@pytest.mark.local
def test_classify_real_cli_quota_and_auth_samples() -> None:
    quota_raw = (SAMPLES_ERR_DIR / "quota_limit.json").read_text(encoding="utf-8")
    quota_data = json.loads(quota_raw)
    err1 = classify_cli_error(
        "claude_cli",
        quota_raw,
        "",
        api_error_status=quota_data.get("api_error_status"),
        result_text=quota_data.get("result", ""),
    )
    assert isinstance(err1, ProviderQuotaExhausted)
    assert err1.provider == "claude_cli"
    assert err1.retry_after_s == 45 * 60

    auth_raw = (SAMPLES_ERR_DIR / "auth_required.json").read_text(encoding="utf-8")
    auth_data = json.loads(auth_raw)
    err2 = classify_cli_error(
        "claude_cli",
        auth_raw,
        "",
        api_error_status=auth_data.get("api_error_status"),
        result_text=auth_data.get("result", ""),
    )
    assert isinstance(err2, ProviderAuthError)
    assert err2.provider == "claude_cli"


@pytest.mark.local
def test_strict_json_schema_adds_additional_properties_false() -> None:
    schema = pydantic_to_strict_json_schema(ShotDescriptionsResponse)
    assert schema["additionalProperties"] is False
    assert "shots" in schema["required"]
