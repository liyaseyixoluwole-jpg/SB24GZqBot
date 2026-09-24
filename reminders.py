"""
Natural-language parsing for reminder times.
"""
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pytz

TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Africa/Algiers"))

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_relative(text: str) -> Optional[timedelta]:
    """Parse 'in 30 minutes', 'in 2 hours 15 min', 'in 1 day 3 hours'."""
    pattern = re.compile(
        r"(\d+)\s*(second|sec|s|minute|min|m|hour|hr|h|day|d|week|w)s?\b",
        re.IGNORECASE,
    )
    matches = pattern.findall(text)
    if not matches:
        return None

    delta = timedelta()
    for value, unit in matches:
        v = int(value)
        u = unit.lower()
        if u in ("second", "sec", "s"):
            delta += timedelta(seconds=v)
        elif u in ("minute", "min", "m"):
            delta += timedelta(minutes=v)
        elif u in ("hour", "hr", "h"):
            delta += timedelta(hours=v)
        elif u in ("day", "d"):
            delta += timedelta(days=v)
        elif u in ("week", "w"):
            delta += timedelta(weeks=v)
    return delta if delta.total_seconds() > 0 else None


def parse_time_hhmm(text: str) -> Optional[Tuple[int, int]]:
    """Extract HH:MM from text. Returns (hour, minute) or None."""
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h < 24 and 0 <= mi < 60:
        return h, mi
    return None


def parse_weekly(text: str) -> Optional[Tuple[str, int, int]]:
    """Parse 'every monday at 09:00'. Returns (day_name, hour, minute)."""
    lower = text.lower()
    day = next((d for d in WEEKDAYS if d in lower), None)
    if not day:
        return None
    hhmm = parse_time_hhmm(text)
    if not hhmm:
        return None
    h, mi = hhmm
    return day, h, mi


def parse_daily(text: str) -> Optional[Tuple[int, int]]:
    """Parse 'every day at 08:30' or 'daily at 20:00'. Returns (hour, minute)."""
    lower = text.lower()
    if "daily" not in lower and "every day" not in lower and "everyday" not in lower:
        return None
    return parse_time_hhmm(text)


def next_daily_datetime(hour: int, minute: int) -> datetime:
    now = datetime.now(TIMEZONE)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def next_weekly_datetime(day_name: str, hour: int, minute: int) -> datetime:
    now = datetime.now(TIMEZONE)
    target = WEEKDAYS[day_name]
    days_ahead = (target - now.weekday()) % 7
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidate += timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate
