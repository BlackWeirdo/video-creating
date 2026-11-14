"""Daily USD budget checking and AI usage recording in SQLite (Phase 04 & Phase 18)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from videocreator.ai.base import BudgetExceeded, RouteKind
from videocreator.config import Settings
from videocreator.db import get_conn, query_one


def today_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def estimate_token_cost(
    settings: Settings,
    model: str,
    units_in: int,
    units_out: int,
) -> float:
    """Calculates USD cost from `config.toml` `[prices.<model>]`."""
    price = settings.prices.get(model)
    if price is None:
        return 0.0
    cost = (
        (max(0, units_in) * float(price.input_per_million_usd))
        + (max(0, units_out) * float(price.output_per_million_usd))
    ) / 1_000_000.0
    return round(cost, 6)


def get_daily_api_spend(
    db_file: Path,
    *,
    bucket: str = "daily",
    day: str | None = None,
) -> float:
    """Returns total API USD spent on `day` for the given budget bucket (`daily`, `generative`, `studio`)."""
    target_day = day or today_utc_str()
    if bucket == "generative":
        row = query_one(
            db_file,
            """
            SELECT COALESCE(SUM(cost_usd), 0.0) AS spent
            FROM ai_usage
            WHERE day = ? AND route = 'api' AND kind = 'videogen'
            """,
            (target_day,),
        )
    elif bucket == "studio":
        row = query_one(
            db_file,
            """
            SELECT COALESCE(SUM(cost_usd), 0.0) AS spent
            FROM ai_usage
            WHERE day = ? AND route = 'api' AND kind = 'studio'
            """,
            (target_day,),
        )
    else:
        row = query_one(
            db_file,
            """
            SELECT COALESCE(SUM(cost_usd), 0.0) AS spent
            FROM ai_usage
            WHERE day = ? AND route = 'api' AND kind NOT IN ('videogen', 'studio')
            """,
            (target_day,),
        )
    return float(row["spent"]) if row else 0.0


def check_budget(
    db_file: Path,
    settings: Settings,
    *,
    kind: str = "writer",
    estimated_cost_usd: float = 0.0,
    day: str | None = None,
) -> float:
    """Checks that the daily API budget has not been reached; raises `BudgetExceeded` if exceeded."""
    target_day = day or today_utc_str()
    if kind == "videogen":
        bucket = "generative"
        limit_usd = float(settings.budget.generative_daily_usd)
    elif kind == "studio":
        bucket = "studio"
        limit_usd = float(settings.budget.studio_daily_usd)
    else:
        bucket = "daily"
        limit_usd = float(settings.budget.daily_usd)

    spent = get_daily_api_spend(db_file, bucket=bucket, day=target_day)
    if spent >= limit_usd or (estimated_cost_usd > 0 and (spent + estimated_cost_usd) > limit_usd):
        raise BudgetExceeded(
            f"Daily {bucket} API budget exceeded on {target_day}: "
            f"spent=${spent:.4f}, limit=${limit_usd:.2f}"
        )
    return spent


def record_usage(
    db_file: Path,
    *,
    provider: str,
    model: str,
    kind: str,
    route: RouteKind = "api",
    units_in: int = 0,
    units_out: int = 0,
    cost_usd: float = 0.0,
    day: str | None = None,
) -> int:
    """Records an AI call into `ai_usage`. Subscription calls always record `cost_usd = 0.0`."""
    target_day = day or today_utc_str()
    actual_cost = 0.0 if route != "api" else round(max(0.0, float(cost_usd)), 6)
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO ai_usage (
                day, role, provider, model, route, kind, input_units, output_units, cost_usd
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_day,
                kind,
                provider,
                model,
                route,
                kind,
                int(units_in),
                int(units_out),
                actual_cost,
            ),
        )
        return int(cur.lastrowid or 0)
