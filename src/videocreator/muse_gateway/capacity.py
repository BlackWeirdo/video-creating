"""Multi-account concurrency capacity & per-account daily safety cap calculator."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from videocreator.ai.budget import app_timezone, budget_day
from videocreator.config_ai import MuseGatewayConfig
from videocreator.db import query_one
from videocreator.timeutil import UTC_ISO_FORMAT


def compute_gateway_capacity(
    pool_state: dict[str, Any] | None,
    cfg: MuseGatewayConfig,
    *,
    discover_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculates parallel task slot ceiling (`min(max_parallel, ready_accounts * renders_per_account)`)."""
    renders_per_acc = max(1, int(cfg.renders_per_account))
    max_par = max(1, int(cfg.max_parallel))

    if pool_state and isinstance(pool_state.get("accounts"), list):
        accounts = [a for a in pool_state["accounts"] if isinstance(a, dict)]
        enabled_accs = [a for a in accounts if a.get("enabled", True) and a.get("status") != "disabled"]
        eligible = [
            a
            for a in enabled_accs
            if str(a.get("status") or "ready") in ("ready", "busy", "queued")
        ]
        cooling = [
            a
            for a in enabled_accs
            if str(a.get("status") or "") == "cooldown"
            and str(a.get("cooldownReason") or "") != "auth"
        ]
        earliest_cd_ms = min(
            (int(a.get("cooldownRemainingMs") or 0) for a in cooling),
            default=0,
        )
        capacity = min(max_par, len(eligible) * renders_per_acc)
        return {
            "total_accounts": len(accounts),
            "eligible_accounts": len(eligible),
            "cooling_accounts": len(cooling),
            "capacity": capacity,
            "earliest_cooldown_s": max(60, earliest_cd_ms // 1000) if cooling else 1800,
        }

    disc_accs = (discover_info or {}).get("accounts")
    if isinstance(disc_accs, dict) and "ready" in disc_accs:
        ready_cnt = max(0, int(disc_accs.get("ready") or 0))
        total_cnt = max(ready_cnt, int(disc_accs.get("total") or 0))
        return {
            "total_accounts": total_cnt,
            "eligible_accounts": ready_cnt,
            "cooling_accounts": max(0, total_cnt - ready_cnt),
            "capacity": min(max_par, ready_cnt * renders_per_acc),
            "earliest_cooldown_s": 900,
        }

    # Remote mode without /api/pool: trust configured max_parallel
    est_accs = max(1, max_par // renders_per_acc)
    return {
        "total_accounts": est_accs,
        "eligible_accounts": est_accs,
        "cooling_accounts": 0,
        "capacity": max_par,
        "earliest_cooldown_s": 900,
    }


def next_local_midnight_utc_iso(db_file: Path) -> str:
    tz = ZoneInfo(app_timezone(db_file))
    now_local = datetime.now(tz)
    tomorrow = (now_local + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return tomorrow.astimezone(ZoneInfo("UTC")).strftime(UTC_ISO_FORMAT)


def is_daily_account_cap_reached(
    db_file: Path,
    cfg: MuseGatewayConfig,
    *,
    kind: str,
    eligible_accounts: int,
) -> bool:
    """Checks daily safety cap (`daily_cap_<kind>_per_account * eligible_accounts`) to protect Muse accounts."""
    if kind == "video":
        per_acc = int(cfg.daily_cap_video_per_account)
    elif kind == "image":
        per_acc = int(cfg.daily_cap_image_per_account)
    elif kind == "audio":
        per_acc = int(cfg.daily_cap_audio_per_account)
    else:
        return False
    if per_acc <= 0:
        return False

    total_cap = max(1, eligible_accounts) * per_acc
    today_prefix = budget_day(db_file)
    row = query_one(
        db_file,
        """
        SELECT COUNT(*) AS c
        FROM muse_tasks
        WHERE kind = ?
          AND status IN ('submitted', 'importing', 'succeeded')
          AND substr(COALESCE(submitted_at, created_at), 1, 10) = ?
        """,
        (kind, today_prefix),
    )
    used_today = int(row["c"]) if row else 0
    return used_today >= total_cap


__all__ = [
    "compute_gateway_capacity",
    "is_daily_account_cap_reached",
    "next_local_midnight_utc_iso",
]
