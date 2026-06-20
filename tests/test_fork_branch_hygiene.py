"""Tests for tools.fork_branch_hygiene — read-only branch-staleness triage.
Offline, stdlib + pytest only. Import via `from tools.<module> import ...`
(empty conftest.py at the worktree root makes that importable)."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path

from tools.fork_branch_hygiene import (
    ACTIVE, AMBIGUOUS, DEFAULT_PROTECT, MERGED, STALE, Record,
    classify, classify_all, main, parse_json, parse_tsv, rank,
    read_records, render, render_json, render_text, selfcheck,
)

DAY = 86400
NOW = 1_700_000_000
TOOL_PATH = Path(__file__).resolve().parent.parent / "tools" / "fork_branch_hygiene.py"

FIXTURE_TSV = (
    "# refname\tcommitterdate\tupstream_track\tmerged\n"
    f"feature/merged-old\t{NOW - 200 * DAY}\t\ttrue\n"
    f"chore/stale-dead\t{NOW - 200 * DAY}\t\tfalse\n"
    f"wip/ambiguous-ahead\t{NOW - 200 * DAY}\t[ahead 3]\tfalse\n"
    f"feature/active-recent\t{NOW - 5 * DAY}\t[ahead 1]\tfalse\n"
    f"main\t{NOW - 365 * DAY}\t[ahead 9]\tfalse\n"
)
FIXTURE_JSON = json.dumps([
    {"name": "feature/merged-old", "committerdate": NOW - 200 * DAY, "merged": True},
    {"name": "chore/stale-dead", "committerdate": NOW - 200 * DAY, "merged": False},
    {"name": "wip/ambiguous-ahead", "committerdate": NOW - 200 * DAY, "merged": False, "ahead": True},
    {"name": "feature/active-recent", "committerdate": NOW - 5 * DAY, "merged": False, "ahead": True},
    {"name": "main", "committerdate": NOW - 365 * DAY, "merged": False, "ahead": True},
])

def _lbl(name, merged, ahead, age_days):
    return classify(Record(name, NOW - age_days * DAY, merged, ahead), NOW, 90, DEFAULT_PROTECT)

def test_classify_each_label_and_boundary():
    assert _lbl("f", True, False, 200).label == MERGED
    assert _lbl("f", False, False, 200).label == STALE
    assert _lbl("f", False, True, 200).label == AMBIGUOUS
    assert _lbl("f", False, True, 5).label == ACTIVE
    assert _lbl("f", False, False, 90).label == ACTIVE   # boundary inclusive
    assert _lbl("f", False, False, 91).label == STALE

def test_protected_default_and_glob_force_active():
    assert _lbl("main", False, False, 999).label == ACTIVE
    r = Record("release/v1", NOW - 999 * DAY, False, False)
    assert classify(r, NOW, 90, DEFAULT_PROTECT + ("release/*",)).label == ACTIVE

def test_parse_tsv_inference_and_overrides():
    assert parse_tsv(f"feat\t{NOW}\t\n")[0].merged is True          # empty track => merged-ish
    assert parse_tsv(f"feat\t{NOW}\t[gone]\n")[0].merged is True    # gone => merged-ish
    a = parse_tsv(f"feat\t{NOW}\t[ahead 2]\n")[0]
    assert a.ahead is True and a.merged is False
    assert parse_tsv(f"feat\t{NOW}\t[ahead 2]\ttrue\n")[0].merged is True  # explicit override
    assert len(parse_tsv(f"# header\n\nfeat\t{NOW}\t\n")) == 1      # skip comment/blank
    assert len(parse_json(FIXTURE_JSON)) == 5
    assert len(read_records(FIXTURE_JSON)) == 5 and len(read_records(FIXTURE_TSV)) == 5  # autodetect

def test_parse_tsv_rejects_malformed_row():
    try:
        parse_tsv("only-one-column\n")
    except ValueError:
        return
    raise AssertionError("expected ValueError")

def test_rank_label_order_and_oldest_first():
    labels = [r.label for r in rank(classify_all(parse_tsv(FIXTURE_TSV), NOW, 90, DEFAULT_PROTECT))]
    assert labels.index(MERGED) < labels.index(STALE) < labels.index(AMBIGUOUS) < labels.index(ACTIVE)
    recs = [Record("young", NOW - 100 * DAY, False, False), Record("old", NOW - 300 * DAY, False, False)]
    assert [r.record.name for r in rank(classify_all(recs, NOW, 90, DEFAULT_PROTECT))] == ["old", "young"]

def test_deterministic_and_tsv_json_identical():
    recs = parse_tsv(FIXTURE_TSV)
    a = render_text(classify_all(recs, NOW, 90, DEFAULT_PROTECT))
    b = render_text(classify_all(list(reversed(recs)), NOW, 90, DEFAULT_PROTECT))
    j = render_text(classify_all(read_records(FIXTURE_JSON), NOW, 90, DEFAULT_PROTECT))
    assert a == b == j

def test_render_text_counts_and_branches():
    out = render_text(classify_all(read_records(FIXTURE_TSV), NOW, 90, DEFAULT_PROTECT))
    assert "total=5" in out
    for tok in ("MERGED=1", "STALE=1", "AMBIGUOUS=1", "ACTIVE=2",
                "feature/merged-old", "chore/stale-dead", "wip/ambiguous-ahead", "main"):
        assert tok in out

def test_render_json_valid_advisory_and_unknown_format():
    payload = json.loads(render_json(classify_all(read_records(FIXTURE_JSON), NOW, 90, DEFAULT_PROTECT)))
    assert payload["advisory"] is True and payload["read_only"] is True and payload["total"] == 5
    assert payload["counts"] == {MERGED: 1, STALE: 1, AMBIGUOUS: 1, ACTIVE: 2}
    assert payload["branches"][0]["label"] == MERGED  # most-prunable first
    try:
        render([], fmt="xml")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown format")

def test_labels_are_advisory_no_destructive_verbs():
    out = render_text(classify_all(read_records(FIXTURE_TSV), NOW, 90, DEFAULT_PROTECT)).lower()
    for verb in ("delete", "git push", "rm ", "force-delete", "prune now"):
        assert verb not in out

def test_selfcheck_green():
    assert selfcheck() == 0
    assert main(["--selfcheck"]) == 0

def test_main_reads_file_and_writes_out(tmp_path, capsys):
    src = tmp_path / "branches.tsv"
    src.write_text(FIXTURE_TSV, encoding="utf-8")
    out_file = tmp_path / "report.txt"
    rc = main([str(src), "--now", str(NOW), "--out", str(out_file)])
    captured = capsys.readouterr().out
    assert rc == 0 and "total=5" in captured
    assert out_file.read_text(encoding="utf-8") == captured  # --out == stdout

def test_main_e2e_tsv_json_equivalent(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(FIXTURE_TSV))
    main(["-", "--now", str(NOW), "--json"])
    from_tsv = json.loads(capsys.readouterr().out)
    monkeypatch.setattr("sys.stdin", io.StringIO(FIXTURE_JSON))
    main(["-", "--now", str(NOW), "--json"])
    from_json = json.loads(capsys.readouterr().out)
    assert from_tsv["total"] == 5
    assert {b["name"]: b["label"] for b in from_tsv["branches"]} == \
           {b["name"]: b["label"] for b in from_json["branches"]}
_STDLIB_ALLOWED = {"__future__", "argparse", "json", "sys", "dataclasses",
                   "fnmatch", "difflib", "time"}

def test_stdlib_only_imports():
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= _STDLIB_ALLOWED, f"non-stdlib imports: {imported - _STDLIB_ALLOWED}"

def test_no_side_effect_apis_and_no_files(tmp_path, monkeypatch):
    src = TOOL_PATH.read_text(encoding="utf-8")
    for banned in ("subprocess", "socket", "urllib", "os.system", "os.remove", "shutil", "requests"):
        assert banned not in src, f"banned API referenced: {banned}"
    monkeypatch.chdir(tmp_path)
    before = set(os.listdir(tmp_path))
    assert render_text(classify_all(read_records(FIXTURE_TSV), NOW, 90, DEFAULT_PROTECT))
    assert set(os.listdir(tmp_path)) == before  # no files created
