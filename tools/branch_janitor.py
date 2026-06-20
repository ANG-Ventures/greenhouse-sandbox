"""branch_janitor: read-only stale-branch triage reporter for a git fork.

Reads a JSON snapshot of branches + PR states and emits a ranked, read-only
report plus an INERT (fully commented) delete script a human may opt into. Never
mutates any branch or remote. Stdlib only, Python 3.11+.

Classes (PRD D3/D4), triage-first: merged (merged flag / ancestor of default /
pr_state==merged) > closed-pr (PR closed unmerged) > stale (idle >= --stale-days
AND behind default) > active. Input JSON: {"default_branch", "now"?, "branches":
[{"name","tip_sha","last_commit_iso","pr_state", merged?, ancestor_of_default?,
behind_default?}]}.
"""

import argparse
import datetime
import json
import sys

# Triage-first ordering: highest delete-confidence first.
CLASS_ORDER = ["merged", "closed-pr", "stale", "active"]

# Embedded known-good snapshot for --selfcheck (deploy health probe).
_SELFCHECK_SNAPSHOT = {
    "default_branch": "main",
    "now": "2026-06-20T00:00:00+00:00",
    "branches": [
        {"name": "feature/done", "tip_sha": "aaa", "last_commit_iso": "2026-06-01T00:00:00+00:00", "pr_state": "merged", "merged": True},
        {"name": "feature/rejected", "tip_sha": "bbb", "last_commit_iso": "2026-05-01T00:00:00+00:00", "pr_state": "closed", "merged": False},
        {"name": "feature/forgotten", "tip_sha": "ccc", "last_commit_iso": "2025-01-01T00:00:00+00:00", "pr_state": "none", "merged": False, "behind_default": True},
        {"name": "feature/live", "tip_sha": "ddd", "last_commit_iso": "2026-06-19T00:00:00+00:00", "pr_state": "open", "merged": False},
    ],
}


class JanitorError(Exception):
    """Raised for malformed input; caller turns it into a clean non-zero exit."""


def _parse_iso(value, field):
    if not isinstance(value, str) or not value:
        raise JanitorError("invalid %s: expected non-empty ISO-8601 string" % field)
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise JanitorError("invalid %s: %r is not ISO-8601 (%s)" % (field, value, exc))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def load(text):
    """Parse + validate the JSON snapshot. Raises JanitorError on bad input."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise JanitorError("input is not valid JSON: %s" % exc)
    if not isinstance(data, dict):
        raise JanitorError("input root must be a JSON object")
    branches = data.get("branches")
    if not isinstance(branches, list):
        raise JanitorError("input must contain a 'branches' list")
    if not branches:
        raise JanitorError("'branches' list is empty; nothing to triage")

    default_branch = data.get("default_branch", "main")
    if not isinstance(default_branch, str) or not default_branch:
        raise JanitorError("'default_branch' must be a non-empty string")

    if "now" in data:
        now = _parse_iso(data["now"], "now")
    else:
        now = datetime.datetime.now(datetime.timezone.utc)

    required = ("name", "tip_sha", "last_commit_iso", "pr_state")
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict):
            raise JanitorError("branch #%d is not an object" % index)
        for key in required:
            if key not in branch:
                raise JanitorError("branch #%d (%r) missing required key %r" % (index, branch.get("name", "?"), key))
        # Validate the date eagerly so malformed dates fail at load time.
        _parse_iso(branch["last_commit_iso"], "last_commit_iso for %r" % branch["name"])

    return {"default_branch": default_branch, "now": now, "branches": branches}


def classify(branch, now, stale_days):
    """Return one of CLASS_ORDER for a single branch dict."""
    if branch.get("merged") is True or branch.get("ancestor_of_default") is True:
        return "merged"
    if branch.get("pr_state") == "merged":
        return "merged"
    if branch.get("pr_state") == "closed":
        return "closed-pr"

    last = _parse_iso(branch["last_commit_iso"], "last_commit_iso")
    age_days = (now - last).total_seconds() / 86400.0
    behind = branch.get("behind_default", True)
    if age_days >= stale_days and behind:
        return "stale"
    return "active"


def rank(branches, now, stale_days):
    """Classify + order triage-first. Returns list of (label, branch) tuples."""
    labelled = [(classify(b, now, stale_days), b) for b in branches]
    rank_index = {label: i for i, label in enumerate(CLASS_ORDER)}
    labelled.sort(key=lambda pair: (rank_index[pair[0]], pair[1]["name"]))
    return labelled


def render(snapshot, stale_days):
    """Render the human-readable triage report as a string."""
    ranked = rank(snapshot["branches"], snapshot["now"], stale_days)
    counts = {label: sum(1 for lbl, _ in ranked if lbl == label) for label in CLASS_ORDER}
    summary = "  ".join("%s=%d" % (label, counts[label]) for label in CLASS_ORDER)
    lines = [
        "branch_janitor triage report",
        "default branch: %s" % snapshot["default_branch"],
        "total branches: %d" % len(ranked),
        "counts: %s" % summary,
        "",
    ]
    for label, branch in ranked:
        lines.append("[%-9s] %s (%s)" % (label, branch["name"], branch["tip_sha"]))
    return "\n".join(lines) + "\n"


def emit_delete_script(snapshot, stale_days):
    """Build the INERT delete script. Every body line is commented out."""
    ranked = rank(snapshot["branches"], snapshot["now"], stale_days)
    deletable = [b["name"] for label, b in ranked if label == "merged"]

    lines = [
        "#!/bin/sh",
        "# branch_janitor delete script -- INERT BY DEFAULT.",
        "# This script does nothing as shipped: every command is commented out.",
        "# To remove the %d merged branch(es), review each line then uncomment it." % len(deletable),
        "#",
    ]
    if deletable:
        lines += ["# git push origin --delete %s" % name for name in deletable]
    else:
        lines.append("# (no merged branches detected; nothing to remove)")
    return "\n".join(lines) + "\n"


def selfcheck():
    """Deploy health probe: 0 on known-good input, non-zero otherwise."""
    try:
        snapshot = load(json.dumps(_SELFCHECK_SNAPSHOT))
        ranked = rank(snapshot["branches"], snapshot["now"], 90)
        labels = {label for label, _ in ranked}
        expected = {"merged", "closed-pr", "stale", "active"}
        if labels != expected:
            return 1
        report = render(snapshot, 90)
        if "counts:" not in report:
            return 1
        script = emit_delete_script(snapshot, 90)
        body = [ln for ln in script.splitlines()[1:] if ln.strip()]
        if any(not ln.startswith("#") for ln in body):
            return 1
        return 0
    except Exception:
        return 1


def _read_input(path):
    if path == "-" or path is None:
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="branch_janitor",
        description="Read-only stale-branch triage reporter (emits an inert delete script).",
    )
    p.add_argument("--input", "-i", default=None, help="JSON snapshot path, or '-'/omit for stdin.")
    p.add_argument("--out", "-o", default=None, help="Write the inert delete script here (default: off).")
    p.add_argument("--stale-days", type=int, default=90, help="Days idle + behind default before 'stale'.")
    p.add_argument("--selfcheck", action="store_true", help="Run the health probe; exit 0 good / non-zero bad.")
    args = p.parse_args(argv)

    if args.selfcheck:
        return selfcheck()

    try:
        snapshot = load(_read_input(args.input))
        report = render(snapshot, args.stale_days)
        sys.stdout.write(report)
        if args.out:
            script = emit_delete_script(snapshot, args.stale_days)
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(script)
    except (JanitorError, OSError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
