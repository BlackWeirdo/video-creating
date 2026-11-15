"""Small time helpers shared across the app: UTC ISO timestamps, the local day, and `HH:MM` parsing."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now(now_dt: datetime | None = None) -> datetime:
    """`now_dt` (or the current time) as an aware UTC datetime; `now_dt` lets callers fix the clock."""
    return (now_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)


def utc_now_iso(now_dt: datetime | None = None) -> str:
    return utc_now(now_dt).strftime(UTC_ISO_FORMAT)


DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"


def zone_or_default(tz_name: str | None) -> ZoneInfo:
    """`tz_name` as a zone; a mistyped name falls back to the default instead of breaking every
    AI call and report that needs "today"."""
    try:
        return ZoneInfo((tz_name or "").strip())
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def local_day(tz_name: str, now_dt: datetime | None = None) -> str:
    """Today's date (`YYYY-MM-DD`) in `tz_name`: daily caps and reports roll over at local midnight."""
    return utc_now(now_dt).astimezone(zone_or_default(tz_name)).strftime("%Y-%m-%d")


def local_day_start_utc_iso(tz_name: str, now_dt: datetime | None = None) -> str:
    """Local midnight of today in `tz_name`, as a UTC ISO timestamp comparable with stored `*_at` columns."""
    tz = zone_or_default(tz_name)
    local_date = utc_now(now_dt).astimezone(tz).date()
    return datetime.combine(local_date, time(0, 0), tzinfo=tz).astimezone(timezone.utc).strftime(UTC_ISO_FORMAT)


def parse_iso_utc(iso_str: str | None) -> datetime | None:
    """Parses an ISO-8601 timestamp (`Z` allowed) into aware UTC; None when missing or invalid."""
    if not iso_str:
        return None
    try:
        clean = str(iso_str).strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_hhmm(val: str, default: tuple[int, int] = (21, 30)) -> tuple[int, int]:
    parts = val.strip().split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return default


def parse_dow_hhmm(val: str, default: tuple[str, int, int] = ("mon", 9, 0)) -> tuple[str, int, int]:
    tokens = val.strip().split()
    if len(tokens) == 2:
        dow = tokens[0].lower()[:3]
        h, m = parse_hhmm(tokens[1], (default[1], default[2]))
        return dow, h, m
    return default
