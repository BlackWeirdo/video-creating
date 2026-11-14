"""Real SQLite tests for AI budget calculation, daily caps, and subscription zero-cost accounting (Phase 04 & 18)."""
from __future__ import annotations

from pathlib import Path

import pytest

from videocreator.ai.base import BudgetExceeded
from videocreator.ai.budget import (
    check_budget,
    estimate_token_cost,
    get_daily_api_spend,
    record_usage,
)
from videocreator.config import Settings
from videocreator.db import migrate


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
