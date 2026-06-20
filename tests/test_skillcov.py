"""Tests for tools/skillcov — Fleet Skill-Coverage Map generator.

Stdlib + pytest only. Runs offline. Imports the tool via the package path
(tools.skillcov); conftest.py at the worktree root makes that importable.
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

from tools import skillcov


# ---------------------------------------------------------------------------
# Fixture-tree builder: one of each kind of skill.
# ---------------------------------------------------------------------------
def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def build_tree(base: Path) -> Path:
    root = base / "tree"
    # code + tests (and a tests/ dir variant via test_ file)
    a = root / "code_and_tests"
    _write(a / "SKILL.md", "---\nname: code_and_tests\n---\nbody\n")
    _write(a / "impl.py", "x = 1\ny = 2\nz = 3\n")          # 3 LOC
    _write(a / "test_impl.py", "def test_x():\n    assert True\n")
    # code, no tests, no validator -> backfill candidate (big LOC)
    b = root / "code_no_tests"
    _write(b / "SKILL.md", "---\nname: code_no_tests\n---\nbody\n")
    _write(b / "big.py", "\n".join(f"line_{i} = {i}" for i in range(10)) + "\n")  # 10 LOC
    # docs only -> no code
    c = root / "docs_only"
    _write(c / "SKILL.md", "---\nname: docs_only\n---\njust docs\n")
    _write(c / "README.md", "# readme\n")
    _write(c / "references" / "notes.py", "should = 'not count as code'\n")  # under references/
    # has validator (file-based) + small code, no tests -> NOT a candidate
    d = root / "has_validator"
    _write(d / "SKILL.md", "---\nname: has_validator\n---\nbody\n")
    _write(d / "tool.sh", "echo hi\n")
    _write(d / "validate.py", "ok = True\n")
    # ships code via frontmatter required_commands, no actual code files
    e = root / "fm_required_commands"
    _write(e / "SKILL.md",
           "---\nname: fm_required_commands\nrequired_commands:\n  - jq\n---\nbody\n")
    return root


# ---------------------------------------------------------------------------
# classify_* unit tests
# ---------------------------------------------------------------------------
def test_classify_code_and_tests(tmp_path):
    root = build_tree(tmp_path)
    recs = {r.name: r for r in (skillcov.classify(d, root)
                                for d in skillcov.discover(root))}
    r = recs["code_and_tests"]
    assert r.ships_code is True
    assert r.has_tests is True
    assert r.has_validator is False
    assert r.loc == 3
    assert r.is_backfill_candidate is False


def test_classify_code_no_tests(tmp_path):
    root = build_tree(tmp_path)
    recs = {r.name: r for r in (skillcov.classify(d, root)
                                for d in skillcov.discover(root))}
    r = recs["code_no_tests"]
    assert r.ships_code is True
    assert r.has_tests is False
    assert r.has_validator is False
    assert r.loc == 10
    assert r.is_backfill_candidate is True


def test_classify_docs_only(tmp_path):
    root = build_tree(tmp_path)
    recs = {r.name: r for r in (skillcov.classify(d, root)
                                for d in skillcov.discover(root))}
    r = recs["docs_only"]
    # .py under references/ must NOT count as shipped code
    assert r.ships_code is False
    assert r.has_tests is False
    assert r.has_validator is False
    assert r.loc == 0
    assert r.is_backfill_candidate is False


def test_classify_has_validator(tmp_path):
    root = build_tree(tmp_path)
    recs = {r.name: r for r in (skillcov.classify(d, root)
                                for d in skillcov.discover(root))}
    r = recs["has_validator"]
    assert r.ships_code is True
    assert r.has_validator is True
    assert r.has_tests is False
    assert r.is_backfill_candidate is False  # validator present -> excluded


def test_classify_frontmatter_required_commands(tmp_path):
    root = build_tree(tmp_path)
    recs = {r.name: r for r in (skillcov.classify(d, root)
                                for d in skillcov.discover(root))}
    r = recs["fm_required_commands"]
    assert r.ships_code is True   # via frontmatter, even with no code files
    assert r.loc == 0
    assert r.has_tests is False
    assert r.has_validator is False
    assert r.is_backfill_candidate is True


# ---------------------------------------------------------------------------
# discover + ranking
# ---------------------------------------------------------------------------
def test_discover_finds_all_skills(tmp_path):
    root = build_tree(tmp_path)
    names = sorted(d.name for d in skillcov.discover(root))
    assert names == sorted([
        "code_and_tests", "code_no_tests", "docs_only",
        "fm_required_commands", "has_validator",
    ])


def test_rank_orders_by_loc_then_name(tmp_path):
    root = build_tree(tmp_path)
    records = [skillcov.classify(d, root) for d in skillcov.discover(root)]
    ranked = skillcov.rank(records)
    names = [r.name for r in ranked]
    # only the two candidates; code_no_tests (10 LOC) before fm (0 LOC)
    assert names == ["code_no_tests", "fm_required_commands"]


# ---------------------------------------------------------------------------
# E2E / integration via main()
# ---------------------------------------------------------------------------
def test_e2e_writes_md_and_json(tmp_path):
    root = build_tree(tmp_path)
    out = tmp_path / "out" / "report.md"
    rc = skillcov.main(["--root", str(root), "--out", str(out), "--json"])
    assert rc == 0
    md = out.read_text(encoding="utf-8")
    assert "# Fleet Skill-Coverage Map" in md
    assert "Total skills scanned: 5" in md
    assert "code_no_tests" in md
    # JSON sidecar parses and mirrors the records
    j = json.loads((tmp_path / "out" / "report.md.json").read_text(encoding="utf-8"))
    assert j["summary"]["total_skills"] == 5
    assert j["summary"]["code_shipping"] == 4   # all but docs_only
    assert j["summary"]["with_tests"] == 1
    assert j["summary"]["with_validator"] == 1
    backfill = [r["name"] for r in j["backfill_top20"]]
    assert backfill == ["code_no_tests", "fm_required_commands"]


def test_e2e_stdout_when_no_out(tmp_path):
    root = build_tree(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = skillcov.main(["--root", str(root)])
    assert rc == 0
    assert "# Fleet Skill-Coverage Map" in buf.getvalue()


# ---------------------------------------------------------------------------
# Invariants / adversarial
# ---------------------------------------------------------------------------
def test_selfcheck_exit_zero():
    assert skillcov.main(["--selfcheck"]) == 0


def test_missing_root_exit2(tmp_path):
    missing = tmp_path / "does_not_exist"
    assert skillcov.main(["--root", str(missing), "--out",
                          str(tmp_path / "r.md")]) == 2


def test_stdlib_only():
    """Every top-level import in the tool resolves to a stdlib module."""
    src_path = Path(skillcov.__file__)
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    stdlib = set(sys.stdlib_module_names)
    nonstd = {m for m in mods if m not in stdlib and m != "__future__"}
    assert nonstd == set(), f"non-stdlib imports found: {nonstd}"


def test_no_write_outside_out(tmp_path):
    """Running the tool must not change any byte/mtime in the scanned tree."""
    root = build_tree(tmp_path)

    def snapshot(base: Path) -> dict:
        snap = {}
        for p in sorted(base.rglob("*")):
            if p.is_file():
                st = p.stat()
                snap[str(p)] = (p.read_bytes(), st.st_mtime_ns, st.st_size)
        return snap

    before = snapshot(root)
    out = tmp_path / "report.md"   # OUTSIDE the scanned root
    rc = skillcov.main(["--root", str(root), "--out", str(out), "--json"])
    assert rc == 0
    after = snapshot(root)
    assert before == after, "scanned tree was modified"
    assert out.exists()


def test_planted_sideeffect_skill(tmp_path):
    """A skill whose body would touch a sentinel IF executed must not run."""
    root = tmp_path / "tree"
    sentinel = tmp_path / "SENTINEL_SHOULD_NOT_EXIST"
    danger = root / "evil"
    _write(danger / "SKILL.md", "---\nname: evil\n---\nbody\n")
    # If skillcov ever imported/exec'd this, the sentinel would be created.
    _write(danger / "evil.py",
           "from pathlib import Path\n"
           f"Path({str(sentinel)!r}).write_text('pwned')\n")
    rc = skillcov.main(["--root", str(root), "--out", str(tmp_path / "r.md")])
    assert rc == 0
    assert not sentinel.exists(), "scanned skill code was executed!"


def test_source_has_no_dynamic_execution():
    """Static guard: no exec/eval/subprocess/importlib of scanned content."""
    src = Path(skillcov.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned_calls = {"exec", "eval", "compile", "__import__"}
    banned_modules = {"subprocess", "importlib", "runpy"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in banned_calls, \
                f"banned call: {node.func.id}"
        if isinstance(node, ast.Import):
            for n in node.names:
                assert n.name.split(".")[0] not in banned_modules, \
                    f"banned import: {n.name}"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned_modules, \
                f"banned import: {node.module}"


def test_symlink_escape_ignored(tmp_path):
    """A symlink in the tree pointing outside root must not be followed."""
    outside = tmp_path / "outside"
    _write(outside / "SKILL.md", "---\nname: outside\n---\nbody\n")
    _write(outside / "secret.py", "leak = True\n")
    root = tmp_path / "tree"
    inner = root / "inner"
    _write(inner / "SKILL.md", "---\nname: inner\n---\nbody\n")
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("symlinks not supported on this platform")
    names = sorted(d.name for d in skillcov.discover(root))
    assert "outside" not in names
    assert names == ["inner"]


def test_deterministic(tmp_path):
    """Same input tree -> byte-identical MD and JSON."""
    root = build_tree(tmp_path)
    records1 = [skillcov.classify(d, root) for d in skillcov.discover(root)]
    records2 = [skillcov.classify(d, root) for d in skillcov.discover(root)]
    assert skillcov.render_md(records1) == skillcov.render_md(records2)
    assert skillcov.render_json(records1) == skillcov.render_json(records2)
