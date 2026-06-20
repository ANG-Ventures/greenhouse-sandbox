"""Tests for tools.prd_dry_audit — the cross-skill DRY duplication mapper.

stdlib + pytest only. Collects and passes offline with no network/third-party deps.
"""
import hashlib
import os

import pytest

from tools.prd_dry_audit import (
    analyze,
    discover,
    exact_blocks,
    label,
    main,
    normalize,
    pairwise_jaccard,
    recommend,
    render_map,
    selfcheck,
    shingles,
    DEFAULT_EXACT_N,
    DEFAULT_HIGH_SIM,
    DEFAULT_MIN_FILES,
    DEFAULT_SHINGLE_K,
)

# --- A fixture skill tree mirroring the real duplication failure modes. ---
# Each shared cross-cutting rule is a >=4-line verbatim block separated by
# file-unique filler, so each rule forms its own detectable cluster. The daemon
# caveat lives in exactly one file (the drift proof) and must NOT cluster.
_BR = (
    "## blast radius\n"
    "classify the blast radius severity.\n"
    "s0 trivial, s1 local change.\n"
    "s2 module-wide, s3 fleet-wide.\n"
    "escalate s3 to a human before proceeding.\n"
)
_DOD = (
    "## definition of done\n"
    "definition of done: tests before code.\n"
    "follow red-green-refactor strictly.\n"
    "tdd is enforced; no merge without green.\n"
    "paste the real verify output into handoff.\n"
)
_DS = (
    "## doc-share\n"
    "share the artifact via doc-share.\n"
    "render it as a dark-mode web link.\n"
    "post the doc-share link into chat.\n"
    "never paste raw html into the channel.\n"
)
FIXTURE = {
    "prd-alpha/SKILL.md": (
        "# prd-alpha\nalpha unique interview guidance here.\n"
        + _BR + "alpha tail filler one two three.\n"
        + _DOD + "alpha closing unique note.\n" + _DS
    ),
    "prd-beta/SKILL.md": (
        "# prd-beta\nbeta unique fanout notes here.\n"
        + _BR + "beta tail filler nine eight seven.\n"
        + _DOD + "beta closing unique note.\n" + _DS
    ),
    "prd-gamma/SKILL.md": (
        "# prd-gamma\ngamma cold-worker context line.\n"
        + _DOD + "gamma middle unique filler.\n"
        "caveat: the daemon is deprecated; the dispatcher runs in the gateway now.\n"
        "gamma trailing unique guidance.\n"
    ),
}


@pytest.fixture()
def skill_tree(tmp_path):
    for rel, body in FIXTURE.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def _hash_tree(root):
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            fp = os.path.join(dirpath, f)
            with open(fp, "rb") as fh:
                out[os.path.relpath(fp, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


# --------------------------- unit-level behavior --------------------------- #
def test_discover_sorted_and_scoped(skill_tree):
    paths = discover(skill_tree)
    rels = [str(p.relative_to(skill_tree)) for p in paths]
    assert rels == sorted(rels)
    assert all(r.startswith("prd-") and r.endswith("SKILL.md") for r in rels)
    assert len(rels) == 3


def test_normalize_strips_markdown():
    lines = normalize("# Heading\n\n- *Bold* item  \n\n> quote\n")
    assert lines == ["heading", "bold item", "quote"]


def test_shingles_and_jaccard_symmetric():
    a = shingles(["x", "y", "z", "w"], 2)
    b = shingles(["x", "y", "z", "w"], 2)
    scores = pairwise_jaccard({"a": a, "b": b})
    assert scores[("a", "b")] == pytest.approx(1.0)


def test_exact_blocks_shared_across_files(skill_tree):
    file_lines = {
        str(p.relative_to(skill_tree)): normalize(p.read_text(encoding="utf-8"))
        for p in discover(skill_tree)
    }
    blocks = exact_blocks(file_lines, DEFAULT_EXACT_N)
    # Some shared block must touch >= 2 files.
    assert any(len(files) >= 2 for _h, files, _s in blocks)


def test_label_taxonomy():
    assert label("classify the blast radius: s0 s1 s2 s3") == "blast-radius-taxonomy"
    assert label("definition of done: tdd enforced") == "definition-of-done-tdd"
    assert label("share the doc-share artifact") == "doc-share-invocation"
    assert label("the daemon is deprecated; dispatcher runs in the gateway") \
        == "daemon-deprecation-caveat"
    assert label("nothing special here at all") == "unlabeled-candidate"


def test_recommend_hoist_and_leave():
    rec, reason = recommend("definition-of-done-tdd", 3, "definition of done text",
                            DEFAULT_MIN_FILES, DEFAULT_HIGH_SIM, 0.5)
    assert rec == "HOIST" and "policy-label" in reason
    rec, reason = recommend("unlabeled-candidate", 1, "lonely line",
                            DEFAULT_MIN_FILES, DEFAULT_HIGH_SIM, 0.9)
    assert rec == "LEAVE" and "cold-worker-context" in reason


# ----------------------- spec invariants / closeout ------------------------ #
def test_deterministic_output(skill_tree):
    """Invariant: same inputs -> byte-identical output."""
    r1, s1, c1 = analyze(skill_tree, DEFAULT_SHINGLE_K, DEFAULT_EXACT_N,
                         DEFAULT_HIGH_SIM, DEFAULT_MIN_FILES)
    m1 = render_map(skill_tree, r1, s1, c1, DEFAULT_HIGH_SIM)
    r2, s2, c2 = analyze(skill_tree, DEFAULT_SHINGLE_K, DEFAULT_EXACT_N,
                         DEFAULT_HIGH_SIM, DEFAULT_MIN_FILES)
    m2 = render_map(skill_tree, r2, s2, c2, DEFAULT_HIGH_SIM)
    assert m1 == m2
    assert "prd_dry_audit" in m1  # body has no timestamp; stable header only


def test_no_writes_outside_own_output(skill_tree, tmp_path):
    """Invariant (read-only): inputs unchanged; only --out is created."""
    before = _hash_tree(skill_tree)
    out = tmp_path / "map_out.md"
    rc = main(["--root", str(skill_tree), "--out", str(out)])
    assert rc == 0
    after = _hash_tree(skill_tree)
    assert before == after, "input skill files must be byte-identical (read-only)"
    assert out.exists() and out.read_text(encoding="utf-8")


def test_selfcheck_creates_no_side_files(skill_tree, tmp_path, monkeypatch):
    """Invariant: selfcheck creates no caches/dotfiles/temp state in cwd."""
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    before = set(os.listdir(workdir))
    rc = selfcheck()
    after = set(os.listdir(workdir))
    assert rc == 0
    assert before == after, "selfcheck must not litter the working directory"


def test_selfcheck_contract(capsys):
    """Contract invariant: --selfcheck exits 0 on bundled known-good fixture."""
    assert main(["--selfcheck"]) == 0


def test_selfcheck_fails_on_corruption(monkeypatch):
    """Contract invariant: non-zero when the known-good expectation breaks."""
    import tools.prd_dry_audit as mod
    # Corrupt the bundled fixture so a required cluster vanishes -> selfcheck must fail.
    broken = {"prd-only/SKILL.md": "# prd-only\nNothing shared with any sibling here.\n"}
    monkeypatch.setattr(mod, "_FIXTURE", broken)
    assert mod.selfcheck() != 0


def test_main_requires_root_without_selfcheck():
    assert main([]) == 2


def test_main_stdout(skill_tree, capsys):
    rc = main(["--root", str(skill_tree)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Cross-Skill Duplication Map" in out
    assert "Duplication clusters" in out


def test_daemon_caveat_not_clustered(skill_tree):
    """The single-file daemon caveat (drift proof) must not appear as a shared cluster."""
    _r, _s, clusters = analyze(skill_tree, DEFAULT_SHINGLE_K, DEFAULT_EXACT_N,
                               DEFAULT_HIGH_SIM, DEFAULT_MIN_FILES)
    assert "daemon-deprecation-caveat" not in {c.label for c in clusters}
