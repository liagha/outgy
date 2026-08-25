import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

import jdatetime

TEHRAN = ZoneInfo("Asia/Tehran")

_DATE_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{1,2})$")


def now() -> datetime:
    return datetime.now(TEHRAN)


def today() -> jdatetime.date:
    return jdatetime.date.fromgregorian(date=now().date())


def iso(date: jdatetime.date) -> str:
    return f"{date.year:04d}/{date.month:02d}/{date.day:02d}"


def window(days: int) -> tuple[str, str]:
    start = today()
    end = start + jdatetime.timedelta(days=days)
    return iso(start), iso(end)


def parse_date(value: str) -> jdatetime.date | None:
    found = _DATE_RE.match(value.strip())
    if not found:
        return None
    year, month, day = (int(part) for part in found.groups())
    try:
        return jdatetime.date(year, month, day)
    except ValueError:
        return None


def parse_time(value: str) -> time | None:
    found = _CLOCK_RE.match(value.strip())
    if not found:
        return None
    hour, minute = int(found[1]), int(found[2])
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)
