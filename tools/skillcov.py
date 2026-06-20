"""skillcov — Fleet Skill-Coverage Map generator (stdlib-only, Python 3.11).

Read-only static audit of a skills tree. Per skill: does it ship code? declare a
readiness validator? have tests? Emits a ranked Markdown report (+ optional JSON
sidecar) of the blind spot. Never executes, imports, or modifies scanned content;
writes only to its --out path.

CLI: python -m tools.skillcov --root DIR --out REPORT.md [--json] [--selfcheck]
Exit: 0 ok / 2 root missing / 1 selfcheck failed.
"""
from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

CODE_EXTS = (".py", ".sh", ".js", ".ts")
DOC_DIRS = ("references", "assets")
VALIDATOR_GLOBS = ("selfcheck*", "readiness*", "validate*", "*_check.*")
VALIDATOR_FM_KEYS = ("readiness", "selfcheck")
CODE_FM_KEYS = ("required_commands",)

RULES_TEXT = (
    "- **ships_code (D-1):** dir has any `*.py`/`*.sh`/`*.js`/`*.ts` outside docs "
    "(excluding `SKILL.md`, `README*`, `references/`/`assets/`), OR `SKILL.md` "
    "frontmatter declares `required_commands`.\n"
    "- **has_validator (D-2):** dir has a file matching `selfcheck*`, `readiness*`, "
    "`validate*`, `*_check.*`, OR frontmatter has a `readiness`/`selfcheck` key.\n"
    "- **has_tests (D-3):** dir has a `test_*.py`/`*_test.py` file or `tests/` dir.\n"
    "- **rank (D-4):** `ships_code AND NOT has_tests AND NOT has_validator`, "
    "sorted by source LOC desc then name asc; top 20.\n"
)


@dataclass(frozen=True)
class SkillRecord:
    name: str
    rel_path: str
    ships_code: bool
    has_validator: bool
    has_tests: bool
    loc: int

    @property
    def is_backfill_candidate(self) -> bool:
        return self.ships_code and not self.has_tests and not self.has_validator


def _is_doc_file(name: str) -> bool:
    low = name.lower()
    return low == "skill.md" or low.startswith("readme")


def _match(name: str, pattern: str) -> bool:
    return fnmatch.fnmatch(name.lower(), pattern.lower())


def _entries(d: Path) -> list[os.DirEntry]:
    try:
        return sorted(os.scandir(d), key=lambda e: e.name)
    except OSError:
        return []


def _read_frontmatter_keys(skill_md: Path) -> set[str]:
    """Top-level YAML frontmatter keys via static line-scan (no yaml, no exec)."""
    keys: set[str] = set()
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return keys
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return keys
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line and not line[0].isspace() and ":" in line:
            key = line.split(":", 1)[0].strip().lower()
            if key:
                keys.add(key)
    return keys


def _count_loc(files: list[Path]) -> int:
    total = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += sum(1 for ln in text.splitlines() if ln.strip())
    return total


def discover(root: Path) -> list[Path]:
    """Skill dirs (any depth) that directly contain SKILL.md. Symlinks never
    followed (escape guard). Deterministic order."""
    found: list[Path] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        for entry in _entries(cur):
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
        sm = cur / "SKILL.md"
        if sm.is_file() and not sm.is_symlink():
            found.append(cur)
    found.sort(key=lambda p: str(p))
    return found


def classify(skill_dir: Path, root: Path) -> SkillRecord:
    """Classify one skill dir by static inspection only."""
    code_files: list[Path] = []
    has_tests = False
    has_validator = False

    sm = skill_dir / "SKILL.md"
    fm = _read_frontmatter_keys(sm) if (sm.is_file() and not sm.is_symlink()) else set()
    ships_code_fm = any(k in fm for k in CODE_FM_KEYS)
    if any(k in fm for k in VALIDATOR_FM_KEYS):
        has_validator = True

    for entry in _entries(skill_dir):
        if entry.is_symlink():
            continue
        name = entry.name
        if entry.is_dir(follow_symlinks=False):
            if name.lower() == "tests":
                has_tests = True
            continue  # references/assets etc. contribute no code/validator
        if _match(name, "test_*.py") or _match(name, "*_test.py"):
            has_tests = True
        if any(_match(name, g) for g in VALIDATOR_GLOBS):
            has_validator = True
        ext = os.path.splitext(name)[1].lower()
        if ext in CODE_EXTS and not _is_doc_file(name):
            code_files.append(Path(entry.path))

    return SkillRecord(
        name=skill_dir.name,
        rel_path=os.path.relpath(skill_dir, root),
        ships_code=ships_code_fm or bool(code_files),
        has_validator=has_validator,
        has_tests=has_tests,
        loc=_count_loc(code_files),
    )


def rank(records: list[SkillRecord]) -> list[SkillRecord]:
    """D-4 backfill ordering: candidates by LOC desc, then name asc."""
    cands = [r for r in records if r.is_backfill_candidate]
    cands.sort(key=lambda r: (-r.loc, r.name))
    return cands


def _pct(num: int, den: int) -> str:
    return "0.0%" if den == 0 else f"{(100.0 * num / den):.1f}%"


def _summary(records: list[SkillRecord]) -> dict:
    total = len(records)
    code = sum(1 for r in records if r.ships_code)
    tested = sum(1 for r in records if r.has_tests)
    validated = sum(1 for r in records if r.has_validator)
    return {
        "total_skills": total,
        "code_shipping": code,
        "with_tests": tested,
        "with_validator": validated,
        "code_no_tests": sum(1 for r in records if r.ships_code and not r.has_tests),
        "pct_code_shipping": _pct(code, total),
        "pct_with_tests": _pct(tested, total),
        "pct_with_validator": _pct(validated, total),
    }


def render_md(records: list[SkillRecord]) -> str:
    recs = sorted(records, key=lambda r: r.name)
    s = _summary(records)
    top = rank(records)[:20]
    out = [
        "# Fleet Skill-Coverage Map", "",
        "Read-only static audit. This report computes coverage; it changes nothing "
        "about the skills it scans.", "",
        "## Summary", "",
        f"- Total skills scanned: {s['total_skills']}",
        f"- Code-shipping: {s['code_shipping']} ({s['pct_code_shipping']})",
        f"- With tests: {s['with_tests']} ({s['pct_with_tests']})",
        f"- With readiness validator: {s['with_validator']} ({s['pct_with_validator']})",
        f"- Code-shipping with NO tests: {s['code_no_tests']}", "",
        "## Top backfill candidates", "",
        "Code-shipping skills with no tests and no readiness validator, ranked by "
        "source LOC (bigger = riskier to leave untested).", "",
        "| Rank | Skill | LOC | Path |", "| ---: | --- | ---: | --- |",
    ]
    if top:
        out += [f"| {i} | {r.name} | {r.loc} | {r.rel_path} |"
                for i, r in enumerate(top, 1)]
    else:
        out.append("| - | (none) | - | - |")
    out += ["", "## Full per-skill table", "",
            "| Skill | Code | Tests | Validator | LOC | Path |",
            "| --- | :---: | :---: | :---: | ---: | --- |"]
    for r in recs:
        out.append(
            f"| {r.name} | {'yes' if r.ships_code else 'no'} | "
            f"{'yes' if r.has_tests else 'no'} | "
            f"{'yes' if r.has_validator else 'no'} | {r.loc} | {r.rel_path} |")
    out += ["", "## Heuristic rules used", "", RULES_TEXT.rstrip("\n"), ""]
    return "\n".join(out)


def render_json(records: list[SkillRecord]) -> str:
    recs = sorted(records, key=lambda r: r.name)
    payload = {
        "summary": _summary(records),
        "skills": [dataclasses.asdict(r) for r in recs],
        "backfill_top20": [dataclasses.asdict(r) for r in rank(records)[:20]],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _build_records(root: Path) -> list[SkillRecord]:
    return [classify(d, root) for d in discover(root)]


def _selfcheck() -> int:
    """Deploy health probe: build a known-good temp tree, assert classification."""
    with tempfile.TemporaryDirectory(prefix="skillcov_selfcheck_") as td:
        base = Path(td)
        a = base / "alpha"; a.mkdir()
        (a / "SKILL.md").write_text("---\nname: alpha\n---\nbody\n", encoding="utf-8")
        (a / "run.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        (a / "test_alpha.py").write_text("def test_x():\n    assert True\n",
                                         encoding="utf-8")
        (a / "selfcheck.sh").write_text("echo ok\n", encoding="utf-8")
        b = base / "bravo"; b.mkdir()
        (b / "SKILL.md").write_text("---\nname: bravo\n---\nbody\n", encoding="utf-8")
        (b / "tool.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
        c = base / "charlie"; c.mkdir()
        (c / "SKILL.md").write_text("---\nname: charlie\n---\ndocs\n", encoding="utf-8")
        (c / "README.md").write_text("# docs\n", encoding="utf-8")

        by = {r.name: r for r in _build_records(base)}
        try:
            assert len(by) == 3, f"expected 3 skills, got {len(by)}"
            assert by["alpha"].ships_code and by["alpha"].has_tests
            assert by["alpha"].has_validator and not by["alpha"].is_backfill_candidate
            assert by["bravo"].ships_code and not by["bravo"].has_tests
            assert not by["bravo"].has_validator and by["bravo"].is_backfill_candidate
            assert not by["charlie"].ships_code and not by["charlie"].has_tests
            assert [r.name for r in rank(list(by.values()))] == ["bravo"]
            assert "# Fleet Skill-Coverage Map" in render_md(list(by.values()))
            assert json.loads(render_json(list(by.values())))["summary"][
                "total_skills"] == 3
        except AssertionError as exc:
            sys.stderr.write(f"selfcheck FAILED: {exc}\n")
            return 1
    sys.stdout.write("selfcheck OK\n")
    return 0


def _default_root() -> Path:
    env = os.environ.get("HERMES_SKILLS_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "skills"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="skillcov",
        description="Fleet Skill-Coverage Map generator (read-only static audit).")
    p.add_argument("--root", default=None,
                   help="Skills root. Default: $HERMES_SKILLS_ROOT then ./skills.")
    p.add_argument("--out", default=None, help="Markdown report output path.")
    p.add_argument("--json", action="store_true",
                   help="Also write JSON sidecar (<out>.json) or to stdout.")
    p.add_argument("--selfcheck", action="store_true",
                   help="Run deploy health probe; exit 0 if healthy.")
    args = p.parse_args(argv)

    if args.selfcheck:
        return _selfcheck()

    root = Path(args.root) if args.root else _default_root()
    if not root.is_dir():
        sys.stderr.write(f"error: skills root does not exist: {root}\n")
        return 2

    records = _build_records(root)
    md = render_md(records)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        if args.json:
            Path(str(out_path) + ".json").write_text(render_json(records),
                                                     encoding="utf-8")
    else:
        sys.stdout.write(md)
        if args.json:
            sys.stdout.write(render_json(records))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
