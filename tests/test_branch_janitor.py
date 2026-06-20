"""Test suite for tools/branch_janitor (offline, stdlib + pytest only)."""

import ast
import json
import os

import pytest

from tools.branch_janitor import (
    JanitorError,
    classify,
    emit_delete_script,
    load,
    main,
    render,
    selfcheck,
)

TOOL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools",
    "branch_janitor.py",
)
NOW = "2026-06-20T00:00:00+00:00"


def _snapshot():
    return {
        "default_branch": "main",
        "now": NOW,
        "branches": [
            {"name": "b-merged", "tip_sha": "m1", "last_commit_iso": "2026-06-01T00:00:00+00:00", "pr_state": "merged", "merged": True},
            {"name": "a-ancestor", "tip_sha": "m2", "last_commit_iso": "2026-06-01T00:00:00+00:00", "pr_state": "open", "merged": False, "ancestor_of_default": True},
            {"name": "c-closed", "tip_sha": "c1", "last_commit_iso": "2026-05-01T00:00:00+00:00", "pr_state": "closed", "merged": False},
            {"name": "d-stale", "tip_sha": "s1", "last_commit_iso": "2025-01-01T00:00:00+00:00", "pr_state": "none", "merged": False, "behind_default": True},
            {"name": "e-active", "tip_sha": "a1", "last_commit_iso": "2026-06-19T00:00:00+00:00", "pr_state": "open", "merged": False},
            {"name": "f-recent-no-pr", "tip_sha": "a2", "last_commit_iso": "2025-01-01T00:00:00+00:00", "pr_state": "none", "merged": False, "behind_default": False},
        ],
    }


def _loaded():
    return load(json.dumps(_snapshot()))


def _branch(name):
    return next(b for b in _snapshot()["branches"] if b["name"] == name)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("b-merged", "merged"),        # merged flag
        ("a-ancestor", "merged"),      # ancestor of default
        ("c-closed", "closed-pr"),     # PR closed unmerged
        ("d-stale", "stale"),          # old + behind default
        ("e-active", "active"),        # recent
        ("f-recent-no-pr", "active"),  # old but NOT behind default -> active
    ],
)
def test_classify(name, expected):
    from datetime import datetime, timezone
    now = datetime.fromisoformat(NOW)
    assert classify(_branch(name), now, 90) == expected


def test_render_end_to_end_counts_and_order():
    report = render(_loaded(), 90)
    assert "counts: merged=2  closed-pr=1  stale=1  active=2" in report
    assert "total branches: 6" in report
    assert "default branch: main" in report
    body = [ln for ln in report.splitlines() if ln.startswith("[")]
    labels = [ln[1:10].strip() for ln in body]
    assert labels == ["merged", "merged", "closed-pr", "stale", "active", "active"]


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        json.dumps({"branches": [{"name": "x", "tip_sha": "1", "pr_state": "open"}]}),  # missing key
        json.dumps({"branches": [{"name": "x", "tip_sha": "1", "last_commit_iso": "nope", "pr_state": "open"}]}),  # bad date
        json.dumps({"branches": []}),  # empty
    ],
)
def test_malformed_input_raises(payload):
    with pytest.raises(JanitorError):
        load(payload)


def test_main_malformed_returns_nonzero(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    rc = main(["--input", str(bad)])
    assert rc == 2
    assert "error:" in capsys.readouterr().err  # clean message, no traceback


def test_delete_script_all_commented():
    script = emit_delete_script(_loaded(), 90)
    body = [ln for ln in script.splitlines() if ln.strip()]
    assert body
    for line in body:
        assert line.startswith("#"), "uncommented line: %r" % line


def test_delete_script_lists_merged_only():
    script = emit_delete_script(_loaded(), 90)
    assert "--delete a-ancestor" in script and "--delete b-merged" in script
    assert "e-active" not in script and "d-stale" not in script


def test_delete_script_empty_when_no_merged():
    snap = load(json.dumps({
        "default_branch": "main", "now": NOW,
        "branches": [{"name": "only-active", "tip_sha": "x1", "last_commit_iso": "2026-06-19T00:00:00+00:00", "pr_state": "open", "merged": False}],
    }))
    script = emit_delete_script(snap, 90)
    for line in [ln for ln in script.splitlines() if ln.strip()]:
        assert line.startswith("#")
    assert "nothing to remove" in script


def test_selfcheck_green():
    assert selfcheck() == 0
    assert main(["--selfcheck"]) == 0


def test_determinism():  # I3
    assert render(_loaded(), 90) == render(load(json.dumps(_snapshot())), 90)


def test_no_third_party_imports():  # I2
    allow = {"argparse", "json", "sys", "datetime", "subprocess", "os", "__future__"}
    tree = ast.parse(open(TOOL_PATH, "r", encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allow, "bad import: %s" % alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            assert node.module.split(".")[0] in allow, "bad import: %s" % node.module


def test_no_uncommented_mutation_in_source():  # I1
    for line in open(TOOL_PATH, "r", encoding="utf-8").read().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "push origin --delete" in stripped:  # only inside an emitted "# ..." literal
            assert '"# git push origin --delete' in stripped, "uncommented mutation: %r" % line


def test_no_stray_writes(tmp_path):  # I4
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_snapshot()), encoding="utf-8")
    before = set(os.listdir(tmp_path))
    rc = main(["--input", str(snap), "--out", str(tmp_path / "delete.sh")])
    assert rc == 0
    assert set(os.listdir(tmp_path)) - before == {"delete.sh"}
