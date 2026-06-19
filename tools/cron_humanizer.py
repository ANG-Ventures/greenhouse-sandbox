"""Tiny cron-expression humanizer proof-of-concept.

Supports standard 5-field cron expressions:
minute hour day-of-month month day-of-week

No dependencies, no network calls. This is intentionally small and incomplete;
it is a PoC for readable summaries of common cron shapes.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass


_MONTHS = {calendar.month_abbr[i].lower(): i for i in range(1, 13)}
_DAYS = {name.lower()[:3]: name for name in calendar.day_abbr}


@dataclass(frozen=True)
class CronParts:
    minute: str
    hour: str
    day_of_month: str
    month: str
    day_of_week: str


def humanize_cron(expression: str) -> str:
    """Return a compact English description for a 5-field cron expression."""
    parts = _parse(expression)

    time_text = _time_phrase(parts.minute, parts.hour)
    date_text = _date_phrase(parts.day_of_month, parts.month, parts.day_of_week)

    if date_text == "every day":
        return f"{time_text} every day"
    return f"{time_text} {date_text}"


def _parse(expression: str) -> CronParts:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron expression must contain exactly 5 fields")
    return CronParts(*fields)


def _time_phrase(minute: str, hour: str) -> str:
    if minute == "*" and hour == "*":
        return "Every minute"

    if hour == "*":
        if minute.startswith("*/"):
            return f"Every {_ordinal_interval(minute[2:], 'minute')}"
        return f"At minute {_number(minute)} of every hour"

    if minute.startswith("*/"):
        return f"Every {_ordinal_interval(minute[2:], 'minute')} during hour {_hour(hour)}"

    return f"At {_clock(hour, minute)}"


def _date_phrase(day_of_month: str, month: str, day_of_week: str) -> str:
    if day_of_month == "*" and month == "*" and day_of_week == "*":
        return "every day"

    pieces: list[str] = []
    if day_of_week != "*":
        pieces.append(f"on {_day_name(day_of_week)}")
    if day_of_month != "*":
        pieces.append(f"on day {_number(day_of_month)} of the month")
    if month != "*":
        pieces.append(f"in {_month_name(month)}")

    return " ".join(pieces)


def _clock(hour: str, minute: str) -> str:
    hour_int = int(_number(hour))
    minute_int = int(_number(minute))
    suffix = "AM" if hour_int < 12 else "PM"
    display_hour = hour_int % 12 or 12
    return f"{display_hour}:{minute_int:02d} {suffix}"


def _hour(hour: str) -> str:
    return f"{int(_number(hour)):02d}:00"


def _number(value: str) -> str:
    if not value.isdigit():
        raise ValueError(f"unsupported cron field: {value!r}")
    return value


def _ordinal_interval(value: str, unit: str) -> str:
    number = int(_number(value))
    plural = unit if number == 1 else f"{unit}s"
    return f"{number} {plural}"


def _month_name(value: str) -> str:
    if value.isdigit():
        month = int(value)
    else:
        month = _MONTHS.get(value.lower())
    if not month or month < 1 or month > 12:
        raise ValueError(f"unsupported month field: {value!r}")
    return calendar.month_name[month]


def _day_name(value: str) -> str:
    if value.isdigit():
        names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        return names[int(value) % 7]
    name = _DAYS.get(value.lower())
    if not name:
        raise ValueError(f"unsupported day-of-week field: {value!r}")
    return name


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Humanize a 5-field cron expression")
    parser.add_argument("expression", help='Example: "*/15 * * * *"')
    args = parser.parse_args()
    print(humanize_cron(args.expression))
