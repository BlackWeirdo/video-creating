"""Quiet hours: non-urgent Telegram messages are held back (`FR-TG-18`)."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from videocreator.config import Settings


def is_quiet_hours(settings: Settings, now_dt: datetime | None = None) -> bool:
    """Returns True if `now_dt` falls inside `settings.telegram.quiet_hours` (default `22:00-07:00` in `schedule.timezone`)."""
    raw = (settings.telegram.quiet_hours or "").strip()
    if "-" not in raw:
        return False
    start_s, end_s = raw.split("-", 1)
    try:
        sh, sm = [int(x) for x in start_s.strip().split(":")]
        eh, em = [int(x) for x in end_s.strip().split(":")]
        t_start = time(sh, sm)
        t_end = time(eh, em)
    except Exception:
        return False

    tz = ZoneInfo(settings.schedule.timezone)
    local_t = (now_dt or datetime.now(timezone.utc)).astimezone(tz).time()
    if t_start <= t_end:
        return t_start <= local_t < t_end
    return local_t >= t_start or local_t < t_end
