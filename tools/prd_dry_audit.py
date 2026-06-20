#!/usr/bin/env python3
"""prd_dry_audit — cross-skill DRY duplication map for the prd-* skill suite.

Read-only. Scans <root>/prd-*/SKILL.md, finds recurring near-duplicate
paragraph blocks that span >=2 distinct skills, clusters them, ranks them,
and prints an advisory duplication map (text or JSON). The tool maps; the
human hoists. It never edits, hoists, or deletes any skill file.

stdlib-only, Python 3.11. See docs/prd-dry-audit.md and REVERSIBILITY.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_ROOT = "/Users/alexgierczyk/.hermes/skills-shared/general"
DEFAULT_THRESHOLD = 0.80
DEFAULT_MIN_SKILLS = 2

# A SKILL.md that just redirects to another skill (rename stub) is not real content.
_RENAME_STUB = re.compile(r"RENAMED\s*[→\-]+\s*load", re.IGNORECASE)

# markdown noise we strip before tokenizing (links, backticks, punctuation, bullets).
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TOKEN = re.compile(r"[a-z0-9]+")


def discover(root: Path) -> dict[str, str]:
    """Map skill_name -> SKILL.md text for every real prd-* skill under root.
    Rename-stub skills are skipped; sorted by name for deterministic order."""
    out: dict[str, str] = {}
    for skill_md in sorted(root.glob("prd-*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        if _RENAME_STUB.search(text):
            continue
        out[skill_md.parent.name] = text
    return out


def normalize(text: str) -> frozenset[str]:
    """Lowercase, drop markdown link targets, tokenize to a bag of word tokens."""
    text = _LINK.sub(r"\1", text.lower())
    return frozenset(_TOKEN.findall(text))


def blockify(text: str) -> list[str]:
    """Split markdown into paragraph blocks (runs between blank lines); list
    bullets join to their lead-in. Returns raw block strings in document order."""
    blocks: list[str] = []
    cur: list[str] = []
    for line in text.splitlines():
        if line.strip():
            cur.append(line.strip())
        elif cur:
            blocks.append(" ".join(cur))
            cur = []
    if cur:
        blocks.append(" ".join(cur))
    return blocks


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


class Block:
    __slots__ = ("skill", "ordinal", "raw", "norm")

    def __init__(self, skill: str, ordinal: int, raw: str):
        self.skill = skill
        self.ordinal = ordinal
        self.raw = raw
        self.norm = normalize(raw)


def collect_blocks(skills: dict[str, str], min_tokens: int = 6) -> list[Block]:
    """Flatten all skills into Block records. Skips blocks too short to matter."""
    blocks: list[Block] = []
    for skill in sorted(skills):
        for ordinal, raw in enumerate(blockify(skills[skill])):
            b = Block(skill, ordinal, raw)
            if len(b.norm) >= min_tokens:
                blocks.append(b)
    return blocks


def cluster(blocks: list[Block], threshold: float) -> list[list[int]]:
    """Single-link cluster block indices by Jaccard >= threshold. Deterministic:
    union-find keeps the lowest index as root; clusters returned sorted."""
    parent = list(range(len(blocks)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri == rj:
            return
        if ri < rj:
            parent[rj] = ri
        else:
            parent[ri] = rj

    n = len(blocks)
    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(blocks[i].norm, blocks[j].norm) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [sorted(g) for g in sorted(groups.values(), key=lambda g: min(g))]


def mean_similarity(blocks: list[Block], idxs: list[int]) -> float:
    """Mean pairwise Jaccard across a cluster (1.0 for a singleton-pair edge)."""
    pairs = [
        jaccard(blocks[a].norm, blocks[b].norm)
        for x, a in enumerate(idxs)
        for b in idxs[x + 1:]
    ]
    return round(sum(pairs) / len(pairs), 4) if pairs else 0.0


def signal_for(skill_count: int, sim: float) -> tuple[str, str]:
    """D-5 advisory signal + one-line rationale. Never a decision."""
    if skill_count >= 3 and sim >= 0.85:
        return "HOIST?", f"policy-shaped: {skill_count} skills, sim {sim:.2f}"
    return "LEAVE?", f"context-shaped: {skill_count} skills, sim {sim:.2f}"


def build_map(skills: dict[str, str], threshold: float, min_skills: int) -> list[dict]:
    """Produce the ranked duplication map: one entry per cross-skill cluster."""
    blocks = collect_blocks(skills)
    rows: list[dict] = []
    for idxs in cluster(blocks, threshold):
        skill_names = sorted({blocks[i].skill for i in idxs})
        if len(skill_names) < min_skills:
            continue  # D-4: within-skill repeats are not drift risk
        sim = mean_similarity(blocks, idxs)
        sig, why = signal_for(len(skill_names), sim)
        rows.append({
            "skills": skill_names,
            "skill_count": len(skill_names),
            "block_count": len(idxs),
            "mean_similarity": sim,
            "signal": sig,
            "rationale": why,
            "sample": blocks[idxs[0]].raw[:160],
            "members": [
                {"skill": blocks[i].skill, "ordinal": blocks[i].ordinal}
                for i in idxs
            ],
        })
    rows.sort(key=lambda r: (-r["skill_count"], -r["mean_similarity"], r["skills"]))
    return rows


def render_text(rows: list[dict]) -> str:
    if not rows:
        return "No cross-skill duplication clusters found.\n"
    out = [f"Cross-skill DRY duplication map — {len(rows)} cluster(s)\n"]
    for n, r in enumerate(rows, 1):
        out.append(
            f"[{n}] {r['signal']:7} skills={r['skill_count']} "
            f"blocks={r['block_count']} sim={r['mean_similarity']:.2f}\n"
            f"    skills: {', '.join(r['skills'])}\n"
            f"    why:    {r['rationale']}\n"
            f"    sample: {r['sample']}\n"
        )
    return "\n".join(out)


# ---- selfcheck: built-in known-good fixture (deploy health probe) ----

# One shared cross-cutting rule (reworded in gamma) + per-skill unique tails,
# plus a rename stub that must be ignored. Built in-memory; no fixture files.
_SHARED = ("Always reproduce the failure before you fix it. Run the failing "
           "path first and observe the real error.")
_REWORD = ("Always reproduce the failure before you fix it; run the failing "
           "path first and observe the real error message.")
_GOOD_FIXTURE = {
    "prd-alpha": f"# prd-alpha\n\n{_SHARED}\n\nAlpha-only guidance nobody else carries.\n",
    "prd-beta": f"# prd-beta\n\n{_SHARED}\n\nBeta-only notes shared with no one.\n",
    "prd-gamma": f"# prd-gamma\n\n{_REWORD}\n\nGamma keeps its own distinct closing tail.\n",
    "prd-old": "# prd-old\n\nRENAMED → load 'prd-alpha' instead.\n",
}


def _selfcheck() -> int:
    """Audit a known-good in-memory fixture; exit 0 iff the expected cross-skill
    cluster surfaces with a HOIST? signal. Teeth: stub skipped, exactly one
    cluster (unique paragraphs don't cluster), deterministic. Non-zero on fail."""
    import tempfile

    def fail(msg: str) -> int:
        print(f"selfcheck FAIL: {msg}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, body in _GOOD_FIXTURE.items():
            (root / name).mkdir()
            (root / name / "SKILL.md").write_text(body, encoding="utf-8")

        skills = discover(root)
        if set(skills) != {"prd-alpha", "prd-beta", "prd-gamma"}:  # stub excluded
            return fail(f"wrong skill set {sorted(skills)}")
        rows = build_map(skills, DEFAULT_THRESHOLD, DEFAULT_MIN_SKILLS)
        if len(rows) != 1:  # only the shared rule; unique tails must not cluster
            return fail(f"expected exactly 1 cluster, got {len(rows)}")
        if rows[0]["skill_count"] != 3 or rows[0]["signal"] != "HOIST?":
            return fail(f"bad top cluster {rows[0]['skill_count']}/{rows[0]['signal']}")
        if render_text(rows) != render_text(build_map(skills, DEFAULT_THRESHOLD, DEFAULT_MIN_SKILLS)):
            return fail("non-deterministic output")
    print("selfcheck OK: cross-skill cluster found, stub skipped, deterministic")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prd_dry_audit",
        description="Cross-skill DRY duplication map for the prd-* skill suite (read-only).",
    )
    p.add_argument("--root", default=DEFAULT_ROOT, help="skills dir to scan")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help="Jaccard match threshold (default 0.80)")
    p.add_argument("--min-skills", type=int, default=DEFAULT_MIN_SKILLS,
                   help="min distinct skills per cluster (default 2)")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p.add_argument("--out", default=None, help="write report to PATH instead of stdout")
    p.add_argument("--selfcheck", action="store_true",
                   help="run deploy health probe on built-in fixture; exit 0 if healthy")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selfcheck:
        return _selfcheck()

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2

    skills = discover(root)
    rows = build_map(skills, args.threshold, args.min_skills)
    report = json.dumps(rows, indent=2, sort_keys=True) if args.json else render_text(rows)

    if args.out:
        Path(args.out).write_text(report if report.endswith("\n") else report + "\n",
                                  encoding="utf-8")
    else:
        sys.stdout.write(report if report.endswith("\n") else report + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
