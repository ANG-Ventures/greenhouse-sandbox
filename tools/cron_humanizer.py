"""cron_humanizer: turn a 5-field cron expression into plain English.

A small, self-contained proof-of-concept. Standard library only.

Field order (standard cron):
    minute  hour  day-of-month  month  day-of-week

Supported per-field syntax:
    *           every value
    */N         step over the whole range
    A-B         inclusive range
    A-B/N       stepped range
    A,B,C       explicit list (items may themselves be ranges/steps)
    N           a single value

day-of-week: 0 or 7 == Sunday.
month and day-of-week accept numeric values; output uses names where helpful.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

MONTHS = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


class CronParseError(ValueError):
    """Raised when a cron expression cannot be parsed."""


@dataclass
class Field:
    raw: str
    lo: int
    hi: int

    def values(self) -> List[int]:
        """Expand this field into the concrete sorted list of values it matches."""
        out: set[int] = set()
        for part in self.raw.split(","):
            out.update(self._expand_part(part))
        return sorted(out)

    def is_wildcard(self) -> bool:
        return self.raw == "*"

    def _expand_part(self, part: str) -> List[int]:
        step = 1
        body = part
        if "/" in part:
            body, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                raise CronParseError(f"bad step in {part!r}")
            if step <= 0:
                raise CronParseError(f"step must be positive in {part!r}")

        if body == "*":
            lo, hi = self.lo, self.hi
        elif "-" in body:
            a, b = body.split("-", 1)
            lo, hi = self._num(a), self._num(b)
            if lo > hi:
                raise CronParseError(f"range start > end in {part!r}")
        else:
            v = self._num(body)
            lo = hi = v

        return list(range(lo, hi + 1, step))

    def _num(self, s: str) -> int:
        try:
            n = int(s)
        except ValueError:
            raise CronParseError(f"expected number, got {s!r}")
        if not (self.lo <= n <= self.hi):
            raise CronParseError(f"{n} out of range [{self.lo},{self.hi}]")
        return n


# (name, lo, hi) for each of the five fields, in order.
_SPEC = [
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day-of-month", 1, 31),
    ("month", 1, 12),
    ("day-of-week", 0, 7),
]


def parse(expr: str) -> List[Field]:
    """Parse a 5-field cron expression into Field objects (validating ranges)."""
    tokens = expr.split()
    if len(tokens) != 5:
        raise CronParseError(f"expected 5 fields, got {len(tokens)}: {expr!r}")
    fields = []
    for tok, (_name, lo, hi) in zip(tokens, _SPEC):
        f = Field(raw=tok, lo=lo, hi=hi)
        f.values()  # validate eagerly
        fields.append(f)
    return fields


def _time_phrase(minute: Field, hour: Field) -> str:
    # Both single fixed values -> exact clock time.
    mvals, hvals = minute.values(), hour.values()
    if minute.is_wildcard() and hour.is_wildcard():
        return "every minute"
    if len(mvals) == 1 and minute.raw != "*" and len(hvals) == 1 and hour.raw != "*":
        return f"at {hvals[0]:02d}:{mvals[0]:02d}"
    if minute.is_wildcard():
        return f"every minute during hour(s) {_join(hvals)}"
    if len(mvals) == 1 and minute.raw != "*" and hour.is_wildcard():
        return f"at minute {mvals[0]} of every hour"
    return f"at minute(s) {_join(mvals)} of hour(s) {_join(hvals)}"


def _dom_phrase(dom: Field) -> str:
    if dom.is_wildcard():
        return ""
    return " on day-of-month " + _join(dom.values())


def _month_phrase(month: Field) -> str:
    if month.is_wildcard():
        return ""
    names = [MONTHS[v] for v in month.values()]
    return " in " + _join_names(names)


def _dow_phrase(dow: Field) -> str:
    if dow.is_wildcard():
        return ""
    names = [DOW[0 if v == 7 else v] for v in dow.values()]
    return " on " + _join_names(names)


def _join(values: List[int]) -> str:
    return ", ".join(str(v) for v in values)


def _join_names(names: List[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def humanize(expr: str) -> str:
    """Return a plain-English description of a 5-field cron expression."""
    minute, hour, dom, month, dow = parse(expr)
    text = _time_phrase(minute, hour)
    text += _dom_phrase(dom)
    text += _month_phrase(month)
    text += _dow_phrase(dow)
    return text


if __name__ == "__main__":
    for sample in ["*/15 * * * *", "0 9 * * 1-5", "30 2 1 * *", "0 0 * 12 0"]:
        print(f"{sample:>15}  ->  {humanize(sample)}")
