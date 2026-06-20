"""Tests for tools/branch_triage.py — stdlib + pytest only, offline.

Covers the spec's Phase 1/2 checks and the constitution invariants:
classification, real-repo E2E, write-verb chokepoint, malformed-input fail-closed,
--selfcheck health probe (green + drift detection), stdlib-only imports, and the
no-write-subcommand-ever invariant.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.branch_triage import (
    WriteVerbError,
    _READ_ONLY_GIT,
    _run_git,
    classify,
    main,
    parse_refs_dump,
    render_json,
    render_text,
    selfcheck,
    sort_report,
)

SEP = "\x1f"
MODULE_PATH = Path(__file__).resolve().parent.parent / "tools" / "branch_triage.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = 1_700_000_000


def _dump(rows: list[tuple[str, int, str]]) -> str:
    return "".join(SEP.join([n, str(ts), tip]) + "\n" for n, ts, tip in rows)


# --- Phase 1: classifier ------------------------------------------------------

def test_classify_merged_stale_active():
    cutoff_old = NOW - 200 * 86400
    recent = NOW - 5 * 86400
    records = parse_refs_dump(
        _dump(
            [
                ("main", NOW - 1 * 86400, "a" * 40),
                ("feature/done", NOW - 10 * 86400, "b" * 40),
                ("chore/old", cutoff_old, "c" * 40),
                ("feature/wip", recent, "e" * 40),
            ]
        )
    )
    rows = classify(
        records,
        now=NOW,
        stale_days=90,
        merged_names=frozenset({"feature/done"}),
        default_branch="main",
    )
    buckets = {r["name"]: r["bucket"] for r in rows}
    assert buckets == {
        "main": "active",          # default branch is never proposed
        "feature/done": "merged",
        "chore/old": "stale",
        "feature/wip": "active",
    }


def test_sort_is_merged_first_then_oldest():
    records = parse_refs_dump(
        _dump(
            [
                ("z-active", NOW - 1 * 86400, "1" * 40),
                ("m-newer", NOW - 2 * 86400, "2" * 40),
                ("m-older", NOW - 300 * 86400, "3" * 40),
                ("s-stale", NOW - 200 * 86400, "4" * 40),
            ]
        )
    )
    rows = classify(
        records,
        now=NOW,
        stale_days=90,
        merged_names=frozenset({"m-newer", "m-older"}),
        default_branch="main",
    )
    order = [r["name"] for r in sort_report(rows)]
    # merged first (oldest first within bucket), then stale, then active
    assert order == ["m-older", "m-newer", "s-stale", "z-active"]


def test_default_branch_never_in_cleanup():
    records = parse_refs_dump(_dump([("main", NOW - 1000 * 86400, "a" * 40)]))
    rows = classify(records, now=NOW, stale_days=90, merged_names=frozenset(), default_branch="main")
    text = render_text(rows, "main", 90)
    assert "git branch -D main" not in text


def test_render_text_has_inert_cleanup_header():
    records = parse_refs_dump(_dump([("feature/done", NOW - 10 * 86400, "b" * 40)]))
    rows = classify(records, now=NOW, stale_days=90, merged_names=frozenset({"feature/done"}), default_branch="main")
    text = render_text(rows, "main", 90)
    assert "# proposed cleanup (NOT executed -- run manually):" in text
    assert "#   git branch -D feature/done" in text
    # the cleanup is commented/inert text, never a bare executable line
    for line in text.splitlines():
        if "git branch -D" in line:
            assert line.lstrip().startswith("#")


def test_render_json_shape():
    import json

    records = parse_refs_dump(_dump([("feature/done", NOW - 10 * 86400, "b" * 40)]))
    rows = classify(records, now=NOW, stale_days=90, merged_names=frozenset({"feature/done"}), default_branch="main")
    payload = json.loads(render_json(rows, "main", 90))
    assert payload["counts"]["merged"] == 1
    assert payload["proposed_cleanup"] == ["git branch -D feature/done"]
    assert payload["default_branch"] == "main"


# --- Negative / adversarial ---------------------------------------------------

def test_write_verb_raises():
    for verb in ("branch", "push", "update-ref", "commit", "checkout", "gc"):
        with pytest.raises(WriteVerbError):
            _run_git("/tmp", [verb, "-D", "anything"])


def test_run_git_empty_args_raises():
    with pytest.raises(WriteVerbError):
        _run_git("/tmp", [])


def test_read_only_allow_list_is_exactly_reads():
    assert _READ_ONLY_GIT == frozenset({"for-each-ref", "merge-base", "rev-parse", "log"})


def test_refs_file_malformed_fails_closed():
    # Wrong field count -> ValueError, no partial output, no traceback to user.
    with pytest.raises(ValueError):
        parse_refs_dump("this is not a valid ref record\n")
    with pytest.raises(ValueError):
        parse_refs_dump("name" + SEP + "notanumber" + SEP + "tip\n")
    with pytest.raises(ValueError):
        parse_refs_dump(SEP + "123" + SEP + "tip\n")  # empty name


def test_main_malformed_refs_file_returns_nonzero(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("garbage line with no separators\n")
    rc = main(["--refs-file", str(bad)])
    assert rc == 1


def test_main_requires_an_input():
    assert main([]) == 2


# --- Constitution invariants --------------------------------------------------

def test_no_write_subcommand_ever():
    """Static guard: the only git subcommands the source executes are read-only.

    Walk the AST for any subprocess.run([... "git" ...]) argv and assert the
    git subcommand token is in the read-only allow-list.
    """
    src = MODULE_PATH.read_text()
    tree = ast.parse(src)
    write_verbs = {"branch", "push", "update-ref", "commit", "checkout", "merge", "rebase", "gc", "reset", "tag", "fetch", "pull", "clone", "add", "rm"}
    found_git_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # find subprocess.run(...) calls
        func = node.func
        is_run = isinstance(func, ast.Attribute) and func.attr == "run"
        if not is_run or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.List):
            continue
        # collect string constants in the argv list
        toks = [e.value for e in first.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if "git" not in toks:
            continue
        found_git_calls += 1
        # no literal write verb may appear as a literal argv token
        for verb in write_verbs:
            assert verb not in toks, f"write verb {verb!r} found in a literal git argv"
    # sanity: we actually inspected the git calls, not zero
    assert found_git_calls >= 1


def test_imports_are_stdlib_only():
    stdlib = set(sys.stdlib_module_names)
    src = MODULE_PATH.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in stdlib, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import (from . import ...) -> local, fine
                continue
            top = (node.module or "").split(".")[0]
            assert top in stdlib, f"non-stdlib import: {node.module}"


# --- Phase 2: --selfcheck health probe ----------------------------------------

def test_selfcheck_function_green():
    assert selfcheck() == 0


def test_selfcheck_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--selfcheck"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_selfcheck_detects_drift(tmp_path):
    """Mutate the expected fixture in an isolated copy; selfcheck must fail.

    We copy the module + fixtures into a tmp tree, corrupt the expected file,
    and run --selfcheck there so the committed fixture is never touched.
    """
    import shutil

    work = tmp_path / "branch_triage_drift"
    (work / "tools").mkdir(parents=True)
    (work / "tests" / "fixtures").mkdir(parents=True)
    shutil.copy(MODULE_PATH, work / "tools" / "branch_triage.py")
    shutil.copy(FIXTURES / "selfcheck_refs.txt", work / "tests" / "fixtures" / "selfcheck_refs.txt")
    drifted = (FIXTURES / "selfcheck_expected.txt").read_text() + "DRIFT\n"
    (work / "tests" / "fixtures" / "selfcheck_expected.txt").write_text(drifted)
    proc = subprocess.run(
        [sys.executable, str(work / "tools" / "branch_triage.py"), "--selfcheck"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


# --- Phase 1: real-repo E2E ---------------------------------------------------

def _git(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env)


def _have_git():
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_git(), reason="git not available")
def test_real_repo_e2e(tmp_path):
    repo = tmp_path / "fork"
    repo.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_GLOBAL": str(tmp_path / "noconfig"),
            "GIT_CONFIG_SYSTEM": str(tmp_path / "noconfig"),
        }
    )
    _git(repo, "init", "-q", "-b", "main", env=env)
    (repo / "f.txt").write_text("base\n")
    _git(repo, "add", "f.txt", env=env)
    _git(repo, "commit", "-q", "-m", "base", env=env)

    # merged branch: branch off main, then merge it back (tip becomes ancestor)
    _git(repo, "checkout", "-q", "-b", "feature/done", env=env)
    (repo / "g.txt").write_text("done\n")
    _git(repo, "add", "g.txt", env=env)
    _git(repo, "commit", "-q", "-m", "done", env=env)
    _git(repo, "checkout", "-q", "main", env=env)
    _git(repo, "merge", "-q", "--no-ff", "feature/done", "-m", "merge done", env=env)

    # active branch: unmerged, recent
    _git(repo, "checkout", "-q", "-b", "feature/wip", env=env)
    (repo / "h.txt").write_text("wip\n")
    _git(repo, "add", "h.txt", env=env)
    _git(repo, "commit", "-q", "-m", "wip", env=env)

    # stale branch: unmerged, backdated commit older than stale-days
    _git(repo, "checkout", "-q", "main", env=env)
    _git(repo, "checkout", "-q", "-b", "chore/stale", env=env)
    (repo / "i.txt").write_text("stale\n")
    _git(repo, "add", "i.txt", env=env)
    old_env = dict(env)
    old_env["GIT_AUTHOR_DATE"] = "2000-01-01T00:00:00"
    old_env["GIT_COMMITTER_DATE"] = "2000-01-01T00:00:00"
    _git(repo, "commit", "-q", "-m", "stale", env=old_env)
    _git(repo, "checkout", "-q", "main", env=env)

    import json

    proc = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--repo", str(repo), "--default-branch", "main", "--json"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    buckets = {b["name"]: b["bucket"] for b in payload["branches"]}
    assert buckets["feature/done"] == "merged"
    assert buckets["feature/wip"] == "active"
    assert buckets["chore/stale"] == "stale"
    assert "git branch -D feature/done" in payload["proposed_cleanup"]
    # invariant: the repo was not mutated by the tool (no branch deleted)
    refs = subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        capture_output=True,
        text=True,
        env=env,
    ).stdout.split()
    assert set(refs) == {"main", "feature/done", "feature/wip", "chore/stale"}
