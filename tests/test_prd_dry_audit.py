"""Tests for tools.prd_dry_audit — offline, stdlib+pytest only, fixture-tree based."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from tools.prd_dry_audit import (
    DEFAULT_MIN_SKILLS,
    DEFAULT_THRESHOLD,
    blockify,
    build_map,
    build_parser,
    collect_blocks,
    discover,
    jaccard,
    main,
    normalize,
    render_text,
)

TOOL = Path(__file__).resolve().parent.parent / "tools" / "prd_dry_audit.py"

SHARED = ("Always reproduce the failure before you fix it. Run the failing "
          "path first and observe the real error.")
SHARED_REWORDED = ("Always reproduce the failure before you fix it; run the failing "
                   "path first and observe the real error message.")


def _skill(name: str, *paragraphs: str) -> str:
    return f"# {name}\n\n" + "\n\n".join(paragraphs) + "\n"


def make_tree(tmp_path: Path, skills: dict[str, str]) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    for name, body in skills.items():
        (root / name).mkdir()
        (root / name / "SKILL.md").write_text(body, encoding="utf-8")
    return root


def fixture_skills() -> dict[str, str]:
    return {
        "prd-alpha": _skill("prd-alpha", SHARED, "Alpha-only unique paragraph here."),
        "prd-beta": _skill("prd-beta", SHARED, "Beta-only unique paragraph here."),
        "prd-gamma": _skill("prd-gamma", SHARED_REWORDED, "Gamma-only unique tail."),
        "prd-old": _skill("prd-old", "RENAMED → load 'prd-alpha' instead."),
    }


# ---- unit ----

def test_normalize_blockify_jaccard():
    norm = normalize("Run the [Dispatcher](http://x) in the `gateway`.")
    assert "dispatcher" in norm and "gateway" in norm and "http" not in norm
    assert blockify("a\nb\n\nc\n") == ["a b", "c"]  # joins lines, splits on blank
    assert jaccard(frozenset("ab"), frozenset("ab")) == 1.0
    assert jaccard(frozenset("ab"), frozenset("cd")) == 0.0


def test_collect_blocks_skips_short(tmp_path):
    skills = {"prd-x": _skill("prd-x", "tiny", "a long enough paragraph with many real words here")}
    assert all(len(b.norm) >= 6 for b in collect_blocks(skills))


# ---- map behaviour ----

def test_discover_skips_rename_stub(tmp_path):
    skills = discover(make_tree(tmp_path, fixture_skills()))
    assert set(skills) == {"prd-alpha", "prd-beta", "prd-gamma"}  # stub excluded


def test_cross_skill_cluster_found_and_signalled(tmp_path):
    rows = build_map(discover(make_tree(tmp_path, fixture_skills())),
                     DEFAULT_THRESHOLD, DEFAULT_MIN_SKILLS)
    assert len(rows) == 1  # only the shared rule clusters
    top = rows[0]
    assert top["skill_count"] == 3 and top["signal"] == "HOIST?"
    assert sorted(top["skills"]) == ["prd-alpha", "prd-beta", "prd-gamma"]
    # per-skill unique tails must never cluster
    assert "unique" not in " ".join(r["sample"] for r in rows)


def test_within_skill_repeat_is_dropped(tmp_path):
    # same paragraph twice in ONE skill -> not cross-skill -> excluded (D-4)
    skills = {
        "prd-alpha": _skill("prd-alpha", SHARED, SHARED, "tail one here now"),
        "prd-beta": _skill("prd-beta", "totally different beta content only"),
    }
    rows = build_map(discover(make_tree(tmp_path, skills)),
                     DEFAULT_THRESHOLD, DEFAULT_MIN_SKILLS)
    assert rows == []


def test_min_skills_arg_filters(tmp_path):
    rows = build_map(discover(make_tree(tmp_path, fixture_skills())),
                     DEFAULT_THRESHOLD, min_skills=4)
    assert rows == []  # nothing spans 4 skills


# ---- §3 invariants (closeout proofs) ----

def test_deterministic(tmp_path):
    skills = discover(make_tree(tmp_path, fixture_skills()))
    a = render_text(build_map(skills, DEFAULT_THRESHOLD, DEFAULT_MIN_SKILLS))
    b = render_text(build_map(skills, DEFAULT_THRESHOLD, DEFAULT_MIN_SKILLS))
    assert a == b


def test_imports_are_stdlib_only():
    roots = set()
    for node in ast.walk(ast.parse(TOOL.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    roots.discard("__future__")
    assert roots <= set(sys.stdlib_module_names), roots


def test_no_writes_to_scanned_dir(tmp_path):
    root = make_tree(tmp_path, fixture_skills())
    before = {p: p.stat().st_mtime_ns for p in sorted(root.rglob("*"))}
    build_map(discover(root), DEFAULT_THRESHOLD, DEFAULT_MIN_SKILLS)
    after = {p: p.stat().st_mtime_ns for p in sorted(root.rglob("*"))}
    assert before == after  # mtimes byte-identical; scan root untouched
    src = TOOL.read_text(encoding="utf-8")
    assert "skill_md.read_text" in src  # skills opened read-only


# ---- CLI / deploy health probe ----

def test_selfcheck_subprocess_exit_zero():
    r = subprocess.run([sys.executable, str(TOOL), "--selfcheck"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_cli_json_text_and_out(tmp_path, capsys):
    root = make_tree(tmp_path, fixture_skills())
    assert main(["--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["skill_count"] == 3
    assert main(["--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "duplication map" in out and "HOIST?" in out
    report = tmp_path / "report.txt"
    assert main(["--root", str(root), "--out", str(report)]) == 0
    assert "HOIST?" in report.read_text(encoding="utf-8")


def test_cli_missing_root_returns_2(tmp_path):
    assert main(["--root", str(tmp_path / "nope")]) == 2


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.threshold == DEFAULT_THRESHOLD and args.min_skills == DEFAULT_MIN_SKILLS
