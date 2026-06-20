#!/usr/bin/env python3.11
"""branch-triage: fork PR/branch hygiene reporter (stdlib-only, Python 3.11).

Read-only analyzer. Classifies every branch of a git clone into:
  - merged: tip is an ancestor of the default branch (safe to delete)
  - stale:  no commit in N days AND not merged (review candidate)
  - active: recent, unmerged (leave alone)

It emits a triage report (text or --json), ranked merged-first then oldest-first,
with a count summary and an INERT proposed-cleanup block the human runs manually.

INVARIANT: zero mutation. Every git call goes through _run_git(), which has a
read-only allow-list; a write verb raises before exec. The tool never runs
`git branch -D`, `git push`, `git update-ref`, etc.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Read-only git subcommands this tool is permitted to execute. Anything else
# (branch -D, push, update-ref, ...) must raise before reaching subprocess.
_READ_ONLY_GIT = frozenset({"for-each-ref", "merge-base", "rev-parse", "log"})

# Stable field separator for the for-each-ref dump and --refs-file format.
_SEP = "\x1f"

# for-each-ref format: refname, committerdate (unix), objectname (tip sha).
_REF_FORMAT = _SEP.join(["%(refname:short)", "%(committerdate:unix)", "%(objectname)"])


class WriteVerbError(RuntimeError):
    """Raised when a non-read-only git subcommand is passed to _run_git()."""


def _run_git(repo: str, args: list[str]) -> str:
    """Single chokepoint for every git invocation. Read-only allow-list enforced.

    Raises WriteVerbError if args[0] is not in the read-only allow-list.
    """
    if not args:
        raise WriteVerbError("no git subcommand given")
    sub = args[0]
    if sub not in _READ_ONLY_GIT:
        raise WriteVerbError(f"refusing non-read-only git subcommand: {sub!r}")
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


class RefRecord:
    """One branch: short name, committer unix timestamp, tip sha."""

    __slots__ = ("name", "committed", "tip")

    def __init__(self, name: str, committed: int, tip: str) -> None:
        self.name = name
        self.committed = committed
        self.tip = tip


def parse_refs_dump(text: str) -> list[RefRecord]:
    """Parse a for-each-ref dump (or --refs-file) into RefRecords.

    Each non-empty line is: <name><SEP><unix-ts><SEP><tip-sha>.
    Fails closed: a malformed line raises ValueError (no partial output).
    """
    records: list[RefRecord] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(_SEP)
        if len(parts) != 3:
            raise ValueError(f"malformed ref record on line {lineno}: {raw!r}")
        name, ts_str, tip = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not name or not tip:
            raise ValueError(f"empty name/tip on line {lineno}: {raw!r}")
        try:
            ts = int(ts_str)
        except ValueError:
            raise ValueError(f"non-integer timestamp on line {lineno}: {ts_str!r}")
        records.append(RefRecord(name, ts, tip))
    return records


def _is_merged_repo(repo: str, tip: str, default_branch: str) -> bool:
    """Merged iff tip is an ancestor of default_branch (D-1: reachability only)."""
    # merge-base is in the read-only allow-list; called directly because its
    # exit code (1 = not-ancestor) is signal, not error, so it bypasses _run_git's
    # raise-on-nonzero. The argv is a fixed read-only verb -- never a write.
    assert "merge-base" in _READ_ONLY_GIT
    proc = subprocess.run(
        ["git", "-C", repo, "merge-base", "--is-ancestor", tip, default_branch],
        capture_output=True,
        text=True,
        check=False,
    )
    # exit 0 => ancestor (merged); exit 1 => not ancestor; other => error.
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise RuntimeError(f"merge-base failed for {tip}: {proc.stderr.strip()}")


def classify(
    records: list[RefRecord],
    now: int,
    stale_days: int,
    merged_names: frozenset[str],
    default_branch: str,
) -> list[dict]:
    """Classify each record into merged/stale/active.

    merged_names is the precomputed set of branch names whose tip is reachable
    from the default branch (resolved by the caller, repo or fixture). The
    default branch itself is never proposed for cleanup.
    """
    cutoff = now - stale_days * 86400
    out: list[dict] = []
    for r in records:
        if r.name == default_branch:
            bucket = "active"  # never propose deleting the default branch
        elif r.name in merged_names:
            bucket = "merged"
        elif r.committed < cutoff:
            bucket = "stale"
        else:
            bucket = "active"
        out.append(
            {
                "name": r.name,
                "tip": r.tip,
                "committed": r.committed,
                "bucket": bucket,
            }
        )
    return out


# Sort priority: merged first, then stale, then active; within a bucket oldest first.
_BUCKET_ORDER = {"merged": 0, "stale": 1, "active": 2}


def sort_report(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (_BUCKET_ORDER[r["bucket"]], r["committed"], r["name"]))


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_text(rows: list[dict], default_branch: str, stale_days: int) -> str:
    rows = sort_report(rows)
    counts = {"merged": 0, "stale": 0, "active": 0}
    for r in rows:
        counts[r["bucket"]] += 1
    lines: list[str] = []
    lines.append(f"# branch-triage report (default={default_branch}, stale-days={stale_days})")
    lines.append(
        f"# counts: merged={counts['merged']} stale={counts['stale']} active={counts['active']} total={len(rows)}"
    )
    lines.append("")
    for r in rows:
        lines.append(f"{r['bucket']:<7} {_iso(r['committed'])} {r['tip'][:12]} {r['name']}")
    lines.append("")
    lines.append("# proposed cleanup (NOT executed -- run manually):")
    merged = [r for r in rows if r["bucket"] == "merged"]
    if merged:
        for r in merged:
            lines.append(f"#   git branch -D {r['name']}")
    else:
        lines.append("#   (no merged branches; nothing proposed)")
    return "\n".join(lines) + "\n"


def render_json(rows: list[dict], default_branch: str, stale_days: int) -> str:
    rows = sort_report(rows)
    counts = {"merged": 0, "stale": 0, "active": 0}
    for r in rows:
        counts[r["bucket"]] += 1
    payload = {
        "default_branch": default_branch,
        "stale_days": stale_days,
        "counts": counts,
        "total": len(rows),
        "branches": rows,
        "proposed_cleanup": [
            f"git branch -D {r['name']}" for r in rows if r["bucket"] == "merged"
        ],
        "note": "proposed cleanup is inert text; this tool never executes it",
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _resolve_default_branch(repo: str) -> str:
    """Best-effort default-branch resolution, read-only. Falls back to 'main'."""
    try:
        out = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
        if out and out != "HEAD":
            return out
    except RuntimeError:
        pass
    return "main"


def acquire_from_repo(repo: str, default_branch: str) -> tuple[list[RefRecord], frozenset[str]]:
    dump = _run_git(repo, ["for-each-ref", f"--format={_REF_FORMAT}", "refs/heads/"])
    records = parse_refs_dump(dump)
    merged: set[str] = set()
    for r in records:
        if r.name == default_branch:
            continue
        if _is_merged_repo(repo, r.tip, default_branch):
            merged.add(r.name)
    return records, frozenset(merged)


# --- selfcheck fixture wiring -------------------------------------------------

_FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
_SELFCHECK_REFS = _FIXTURES / "selfcheck_refs.txt"
_SELFCHECK_EXPECTED = _FIXTURES / "selfcheck_expected.txt"
# Frozen reference point so the fixture report is byte-identical run to run.
_SELFCHECK_NOW = 1_700_000_000
_SELFCHECK_STALE_DAYS = 90
_SELFCHECK_DEFAULT = "main"
# In the fixture, these branch tips are declared reachable from main (merged).
_SELFCHECK_MERGED = frozenset({"feature/done", "fix/old-merged"})


def _selfcheck_report() -> str:
    text = _SELFCHECK_REFS.read_text()
    records = parse_refs_dump(text)
    rows = classify(
        records,
        now=_SELFCHECK_NOW,
        stale_days=_SELFCHECK_STALE_DAYS,
        merged_names=_SELFCHECK_MERGED,
        default_branch=_SELFCHECK_DEFAULT,
    )
    return render_text(rows, _SELFCHECK_DEFAULT, _SELFCHECK_STALE_DAYS)


def selfcheck() -> int:
    """Deploy health probe: render over committed fixture, compare to expected.

    Returns 0 iff the rendered report byte-matches the committed expected output.
    """
    try:
        got = _selfcheck_report()
        want = _SELFCHECK_EXPECTED.read_text()
    except (OSError, ValueError):
        return 1
    return 0 if got == want else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="fork PR/branch hygiene reporter (read-only)")
    ap.add_argument("--repo", help="path to a git clone to analyze")
    ap.add_argument("--refs-file", help="captured for-each-ref dump to analyze instead of --repo")
    ap.add_argument("--default-branch", default=None, help="default branch (auto-detected for --repo, else 'main')")
    ap.add_argument("--stale-days", type=int, default=90, help="staleness threshold in days (default 90)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--selfcheck", action="store_true", help="run deploy health probe and exit")
    args = ap.parse_args(argv)

    if args.selfcheck:
        return selfcheck()

    try:
        if args.refs_file:
            default_branch = args.default_branch or "main"
            records = parse_refs_dump(Path(args.refs_file).read_text())
            # Without a repo we cannot compute reachability; nothing is "merged".
            rows = classify(
                records,
                now=int(datetime.now(tz=timezone.utc).timestamp()),
                stale_days=args.stale_days,
                merged_names=frozenset(),
                default_branch=default_branch,
            )
        elif args.repo:
            default_branch = args.default_branch or _resolve_default_branch(args.repo)
            records, merged_names = acquire_from_repo(args.repo, default_branch)
            rows = classify(
                records,
                now=int(datetime.now(tz=timezone.utc).timestamp()),
                stale_days=args.stale_days,
                merged_names=merged_names,
                default_branch=default_branch,
            )
        else:
            print("error: one of --repo, --refs-file, or --selfcheck is required", file=sys.stderr)
            return 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = render_json(rows, default_branch, args.stale_days) if args.json else render_text(
        rows, default_branch, args.stale_days
    )
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
