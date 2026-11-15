"""Real SQLite tests for AI budget calculation, daily caps, and subscription zero-cost accounting (Phase 04 & 18)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from videocreator.ai.base import BudgetExceeded, UnpricedModelError
from videocreator.ai.budget import budget_day, check_budget, estimate_token_cost, get_daily_api_spend, record_usage
from videocreator.config import Settings, save_settings
from videocreator.db import migrate, query_all
from videocreator.paths import get_paths
from videocreator.timeutil import local_day, local_day_start_utc_iso


@pytest.mark.local
def test_subscription_calls_cost_zero_and_do_not_consume_api_budget(tmp_path: Path) -> None:
    db_file = tmp_path / "videocreator.db"
    migrate(db_file)
    settings = Settings()
    settings.budget.daily_usd = 0.01

    # Record a large subscription CLI call -> cost must be forced to 0.0
    record_usage(
        db_file,
        provider="claude_cli",
        model="sonnet",
        kind="writer",
        route="subscription",
        units_in=50_000,
        units_out=4_000,
        cost_usd=0.25,  # even if caller passes client-side estimate, subscription cost is 0.0
        day="2026-11-13",
    )
    assert get_daily_api_spend(db_file, bucket="daily", day="2026-11-13") == 0.0
    # Budget check still passes because subscription calls don't consume API budget
    check_budget(db_file, settings, kind="writer", day="2026-11-13")


@pytest.mark.local
def test_api_budget_cap_blocks_when_daily_limit_reached(tmp_path: Path) -> None:
    db_file = tmp_path / "videocreator.db"
    migrate(db_file)
    settings = Settings()
    settings.budget.daily_usd = 0.01

    cost = estimate_token_cost(settings, "claude-opus-5-5", units_in=2_000, units_out=500)
    # 2000 * $4/M + 500 * $20/M = $0.008 + $0.010 = $0.018
    assert cost == pytest.approx(0.018, rel=1e-4)

    record_usage(
        db_file,
        provider="claude_api",
        model="claude-opus-5-5",
        kind="writer",
        route="api",
        units_in=2_000,
        units_out=500,
        cost_usd=cost,
        day="2026-11-13",
    )

    with pytest.raises(BudgetExceeded, match="Daily daily API budget exceeded"):
        check_budget(db_file, settings, kind="writer", day="2026-11-13")

    # Separate studio and generative budgets remain unaffected
    assert check_budget(db_file, settings, kind="studio", day="2026-11-13") == 0.0
    assert check_budget(db_file, settings, kind="videogen", day="2026-11-13") == 0.0


@pytest.mark.local
def test_unpriced_model_is_blocked_before_the_call(tmp_path: Path) -> None:
    """A model missing from [prices] would be recorded at $0 and never hit the cap (BR-COST-02)."""
    db_file = tmp_path / "app.db"
    migrate(db_file)
    settings = Settings()

    with pytest.raises(UnpricedModelError, match="gemini-9-unknown"):
        check_budget(db_file, settings, kind="writer", model="gemini-9-unknown")
    assert query_all(db_file, "SELECT * FROM ai_usage") == []

    assert check_budget(db_file, settings, kind="writer", model="claude-opus-5-5") == 0.0


@pytest.mark.local
def test_budget_day_rolls_over_at_local_midnight(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    save_settings(paths.config_file, Settings())  # schedule.timezone = Asia/Ho_Chi_Minh

    # 06:00 and 08:00 Vietnam time on the 15th are the same budget day (UTC changes date in between)
    assert budget_day(paths.db_file, datetime(2026, 11, 14, 23, 0, tzinfo=timezone.utc)) == "2026-11-15"
    assert budget_day(paths.db_file, datetime(2026, 11, 15, 1, 0, tzinfo=timezone.utc)) == "2026-11-15"
    # 23:30 Vietnam time on the 15th is still the 15th; 00:30 on the 16th is the 16th
    assert budget_day(paths.db_file, datetime(2026, 11, 15, 16, 30, tzinfo=timezone.utc)) == "2026-11-15"
    assert budget_day(paths.db_file, datetime(2026, 11, 15, 17, 30, tzinfo=timezone.utc)) == "2026-11-16"

    assert local_day("Asia/Ho_Chi_Minh", datetime(2026, 11, 15, 18, 30, tzinfo=timezone.utc)) == "2026-11-16"
    assert (
        local_day_start_utc_iso("Asia/Ho_Chi_Minh", datetime(2026, 11, 15, 18, 30, tzinfo=timezone.utc))
        == "2026-11-15T17:00:00Z"
    )

    # Usage recorded without an explicit day lands on the local day the cap reads
    record_usage(paths.db_file, provider="gemini_api", model="gemini-3.8-flash", kind="writer", cost_usd=0.5)
    row = query_all(paths.db_file, "SELECT day FROM ai_usage")[0]
    assert row["day"] == budget_day(paths.db_file)


@pytest.mark.local
def test_router_skips_an_unpriced_api_model_and_uses_the_next_provider(tmp_path: Path) -> None:
    """The real Gemini provider stops at the price check (before any key or network use); the
    role then falls through to the next provider instead of failing."""
    from pydantic import BaseModel

    from videocreator.ai.gemini import GeminiAPIProvider
    from videocreator.ai.router import RoutedProvider
    from videocreator.secrets_store import SecretsStore

    class Answer(BaseModel):
        text: str

    class NextProvider:
        name = "next_provider"
        route_kind = "subscription"

        def generate_json(self, prompt, schema):  # type: ignore[no-untyped-def]
            return schema.model_validate({"text": "ok"})

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    settings = Settings()
    settings.ai.routes.writer = ["gemini_api", "next_provider"]
    settings.ai.policy.api_fallback = "auto"
    save_settings(paths.config_file, settings)
    unpriced = GeminiAPIProvider(
        paths.db_file, paths.config_file, SecretsStore(paths.secrets_file), role="writer", model="gemini-9-unknown"
    )
    routed = RoutedProvider(
        paths, "writer", provider_overrides={"gemini_api": unpriced, "next_provider": NextProvider()}
    )
    assert routed.generate_json("x", Answer).text == "ok"
    assert routed.last_used_provider == "next_provider"
    assert query_all(paths.db_file, "SELECT * FROM ai_usage") == []


@pytest.mark.local
def test_mistyped_timezone_falls_back_instead_of_breaking_every_ai_call(tmp_path: Path) -> None:
    now = datetime(2026, 11, 15, 18, 30, tzinfo=timezone.utc)
    assert local_day("Asia/Saigon-typo", now) == "2026-11-16"  # default zone (Vietnam), no exception
    assert local_day_start_utc_iso("", now) == "2026-11-15T17:00:00Z"

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    settings = Settings()
    settings.schedule.timezone = "Nowhere/Land"
    save_settings(paths.config_file, settings)
    check_budget(paths.db_file, settings, kind="writer", model="claude-opus-5-5")
    record_usage(paths.db_file, provider="claude_api", model="claude-opus-5-5", kind="writer", cost_usd=0.01)
    assert query_all(paths.db_file, "SELECT cost_usd FROM ai_usage") == [{"cost_usd": 0.01}]


@pytest.mark.local
def test_settings_form_rejects_an_unknown_timezone(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from videocreator.app import create_app
    from videocreator.config import load_settings

    app = create_app(data_dir=tmp_path, start_worker=False)
    with TestClient(app) as client:
        bad = client.post("/settings/config", data={"timezone_name": "Asia/Saigon-typo"}, follow_redirects=False)
        assert bad.headers["location"] == "/settings?saved=bad_timezone"
        ok = client.post("/settings/config", data={"timezone_name": "Asia/Bangkok"}, follow_redirects=False)
        assert ok.headers["location"] == "/settings?saved=config"
    assert load_settings(app.state.paths.config_file).schedule.timezone == "Asia/Bangkok"
