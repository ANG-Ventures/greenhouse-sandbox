#!/usr/bin/env python3.11
"""fork-branch-hygiene: read-only staleness triage for a fork's branch list.
Reads a fed TSV/JSON branch dump, classifies each branch MERGED/STALE/AMBIGUOUS/
ACTIVE, emits a deterministic ranked triage report (most-prunable first). READ-ONLY:
no subprocess/network/git mutation. stdlib-only, Py3.11. --selfcheck = health probe."""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass
from fnmatch import fnmatch

MERGED, STALE, AMBIGUOUS, ACTIVE = "MERGED", "STALE", "AMBIGUOUS", "ACTIVE"
_LABEL_RANK = {MERGED: 0, STALE: 1, AMBIGUOUS: 2, ACTIVE: 3}  # lower => more prunable
DEFAULT_STALE_DAYS = 90
DEFAULT_PROTECT = ("main", "master", "HEAD")
_SECONDS_PER_DAY = 86400

@dataclass(frozen=True)
class Record:
    """One branch's normalized facts; pure data, no I/O."""
    name: str
    committerdate: int  # unix seconds
    merged: bool        # merged into default
    ahead: bool         # has unmerged commits

@dataclass(frozen=True)
class Result:
    """A classified branch: record + advisory label + human reason + age."""
    record: Record
    label: str
    reason: str
    age_days: int

def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "merged", "t"}

def _track_implies_merged(track: str) -> bool:
    # Empty (in sync) or [gone] => nothing unmerged; 'ahead' => unmerged commits.
    t = track.strip()
    if t in ("", "[gone]"):
        return True
    return "ahead" not in t
def _track_implies_ahead(track: str) -> bool:
    return "ahead" in track.strip()

def parse_tsv(text: str) -> list[Record]:
    """TSV: refname<TAB>committerdate_unix<TAB>upstream_track[<TAB>merged_flag].
    Optional 4th column overrides merged inference; blank/'#' lines skipped."""
    records: list[Record] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise ValueError(f"malformed TSV row (need >=2 columns): {raw!r}")
        name = parts[0].strip()
        try:
            committerdate = int(parts[1].strip())
        except ValueError as exc:
            raise ValueError(f"bad committerdate in row {raw!r}: {exc}") from exc
        track = parts[2] if len(parts) >= 3 else ""
        has_flag = len(parts) >= 4 and parts[3].strip() != ""
        merged = _coerce_bool(parts[3]) if has_flag else _track_implies_merged(track)
        records.append(Record(name, committerdate, merged, _track_implies_ahead(track)))
    return records

def parse_json(text: str) -> list[Record]:
    """JSON array of {name, committerdate, merged?, track?, ahead?}; merged/ahead
    inferred from track when absent."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("JSON input must be an array of branch objects")
    records: list[Record] = []
    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            raise ValueError(f"JSON element {i} is not an object")
        name = str(obj["name"]).strip()
        committerdate = int(obj["committerdate"])
        track = str(obj.get("track", ""))
        merged = _coerce_bool(obj["merged"]) if "merged" in obj else _track_implies_merged(track)
        ahead = _coerce_bool(obj["ahead"]) if "ahead" in obj else _track_implies_ahead(track)
        records.append(Record(name, committerdate, merged, ahead))
    return records

def read_records(text: str, fmt: str = "auto") -> list[Record]:  # fmt: auto|tsv|json
    if fmt == "auto":
        fmt = "json" if text.lstrip()[:1] in ("[", "{") else "tsv"
    if fmt == "json":
        return parse_json(text)
    if fmt == "tsv":
        return parse_tsv(text)
    raise ValueError(f"unknown format: {fmt!r}")

def is_protected(name: str, protect_globs: tuple[str, ...]) -> bool:
    return any(fnmatch(name, pat) for pat in protect_globs)

def classify(record: Record, now: int, stale_days: int, protect_globs: tuple[str, ...]) -> Result:
    """Label one branch (pure). Protected->ACTIVE; merged->MERGED; recent->ACTIVE;
    old+ahead->AMBIGUOUS; else STALE."""
    age_days = max(0, (now - record.committerdate) // _SECONDS_PER_DAY)
    if is_protected(record.name, protect_globs):
        return Result(record, ACTIVE, "protected branch", age_days)
    if record.merged:
        return Result(record, MERGED, "merged into default branch", age_days)
    if age_days <= stale_days:
        return Result(record, ACTIVE, f"recent (<= {stale_days}d)", age_days)
    if record.ahead:
        return Result(record, AMBIGUOUS, f"old ({age_days}d) but has unmerged commits", age_days)
    return Result(record, STALE, f"unmerged and untouched {age_days}d", age_days)

def classify_all(records, now, stale_days, protect_globs) -> list[Result]:
    return [classify(r, now, stale_days, protect_globs) for r in records]

def rank(results: list[Result]) -> list[Result]:  # deterministic: label, oldest-first, name
    return sorted(results, key=lambda r: (_LABEL_RANK[r.label], -r.age_days, r.record.name))

def _counts(ordered: list[Result]) -> dict[str, int]:
    c = {MERGED: 0, STALE: 0, AMBIGUOUS: 0, ACTIVE: 0}
    for r in ordered:
        c[r.label] += 1
    return c

def render_text(results: list[Result]) -> str:
    ordered = rank(results)  # deterministic fixed-column, triage-first, advisory only
    c = _counts(ordered)
    lines = [
        "fork-branch-hygiene report (advisory; read-only — no branch is deleted)",
        f"total={len(ordered)} MERGED={c[MERGED]} STALE={c[STALE]} "
        f"AMBIGUOUS={c[AMBIGUOUS]} ACTIVE={c[ACTIVE]}",
        f"{'LABEL':<9} {'AGE_D':>6}  {'BRANCH':<40} REASON",
    ]
    for r in ordered:
        lines.append(f"{r.label:<9} {r.age_days:>6}  {r.record.name:<40} {r.reason}")
    return "\n".join(lines) + "\n"

def render_json(results: list[Result]) -> str:
    ordered = rank(results)  # deterministic JSON, same ranking as text
    branches = [{"name": r.record.name, "label": r.label, "age_days": r.age_days,
                 "committerdate": r.record.committerdate, "merged": r.record.merged,
                 "ahead": r.record.ahead, "reason": r.reason} for r in ordered]
    payload = {"advisory": True, "read_only": True, "total": len(ordered),
               "counts": _counts(ordered), "branches": branches}
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"

def render(results: list[Result], fmt: str = "text") -> str:
    if fmt == "json":
        return render_json(results)
    if fmt == "text":
        return render_text(results)
    raise ValueError(f"unknown render format: {fmt!r}")

_SELFCHECK_NOW = 1_700_000_000
_DAY = _SECONDS_PER_DAY
_SELFCHECK_RECORDS = [
    Record("feature/merged-old", _SELFCHECK_NOW - 200 * _DAY, True, False),
    Record("chore/stale-dead", _SELFCHECK_NOW - 200 * _DAY, False, False),
    Record("wip/ambiguous-ahead", _SELFCHECK_NOW - 200 * _DAY, False, True),
    Record("feature/active-recent", _SELFCHECK_NOW - 5 * _DAY, False, True),
    Record("main", _SELFCHECK_NOW - 365 * _DAY, False, True),
]
_SELFCHECK_GOLDEN = (
    "fork-branch-hygiene report (advisory; read-only — no branch is deleted)\n"
    "total=5 MERGED=1 STALE=1 AMBIGUOUS=1 ACTIVE=2\n"
    "LABEL      AGE_D  BRANCH                                   REASON\n"
    "MERGED       200  feature/merged-old                       merged into default branch\n"
    "STALE        200  chore/stale-dead                         unmerged and untouched 200d\n"
    "AMBIGUOUS    200  wip/ambiguous-ahead                      old (200d) but has unmerged commits\n"
    "ACTIVE       365  main                                     protected branch\n"
    "ACTIVE         5  feature/active-recent                    recent (<= 90d)\n"
)

def selfcheck() -> int:
    """Run the pure pipeline over a bundled fixture vs a golden string. 0 ok, 1 drift."""
    got = render_text(classify_all(list(_SELFCHECK_RECORDS), _SELFCHECK_NOW, 90, DEFAULT_PROTECT))
    if got == _SELFCHECK_GOLDEN:
        print("selfcheck: OK")
        return 0
    import difflib
    diff = "".join(difflib.unified_diff(
        _SELFCHECK_GOLDEN.splitlines(keepends=True), got.splitlines(keepends=True),
        fromfile="golden", tofile="got"))
    print("selfcheck: FAIL", file=sys.stderr)
    print(diff, file=sys.stderr)
    return 1

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only staleness triage for a fork's branch list. "
        "Classifies and reports; never deletes, pushes, or mutates any ref.")
    ap.add_argument("--selfcheck", action="store_true", help="run the deploy health probe and exit")
    ap.add_argument("input", nargs="?", default="-", help="branch-dump path, or '-' for stdin")
    ap.add_argument("--format", choices=["auto", "tsv", "json"], default="auto", help="input format")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON instead of text")
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS, help="staleness threshold (days)")
    ap.add_argument("--now", type=int, default=None, help="reference unix time (default: real now)")
    ap.add_argument("--protect", action="append", default=[], metavar="GLOB", help="extra ACTIVE globs")
    ap.add_argument("--out", default=None, help="also write the report to this file path")
    args = ap.parse_args(argv)
    if args.selfcheck:
        return selfcheck()
    if args.now is None:
        import time
        now = int(time.time())
    else:
        now = args.now
    if args.input == "-":
        text = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as fh:
            text = fh.read()
    records = read_records(text, fmt=args.format)
    protect_globs = tuple(DEFAULT_PROTECT) + tuple(args.protect)
    results = classify_all(records, now, args.stale_days, protect_globs)
    out = render(results, fmt="json" if args.json else "text")
    sys.stdout.write(out)
    if args.out is not None:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
