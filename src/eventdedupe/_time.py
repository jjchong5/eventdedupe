"""Start-time parsing and comparison."""
from __future__ import annotations

import re
from datetime import date, datetime

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOOSE = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{1,2}):(\d{2})")
_COMPACT_OFFSET = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_start(value: object) -> datetime | None:
    """A start time as a datetime, or None for a missing or date-only value.

    Accepts ISO 8601 with or without an offset ("Z", "+02:00", "+0200") and datetime objects.
    A value with an offset becomes an aware datetime, so two listings written in different
    zones compare by instant.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return None
    text = str(value).strip()
    if _DATE_ONLY.match(text):
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = _COMPACT_OFFSET.sub(r"\1:\2", text)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        m = _LOOSE.search(text)
        if not m:
            return None
        try:
            return datetime.fromisoformat(f"{m.group(1)}T{int(m.group(2)):02d}:{m.group(3)}")
        except ValueError:
            return None


def date_of(value: object) -> str | None:
    """The YYYY-MM-DD at the start of a date or datetime value, as written (local date)."""
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    m = re.match(r"\d{4}-\d{2}-\d{2}", str(value).strip())
    return m.group(0) if m else None


def gap_minutes(a: datetime | None, b: datetime | None) -> float | None:
    """Minutes between two starts, or None if either is missing.

    Both aware: compared by instant. Otherwise by wall clock, so a listing that dropped its
    offset still lines up with one that kept it.
    """
    if a is None or b is None:
        return None
    if a.tzinfo is not None and b.tzinfo is not None:
        return abs((a - b).total_seconds()) / 60
    return abs((a.replace(tzinfo=None) - b.replace(tzinfo=None)).total_seconds()) / 60
