#!/usr/bin/env python3
"""prd_dry_audit -- Cross-Skill DRY Duplication Mapper (stdlib only, read-only).

Scans ``prd-*/SKILL.md`` files, clusters recurring cross-cutting blocks, and emits
a deterministic duplication map (markdown). It NEVER rewrites any skill file; it
only reads inputs and writes its own ``--out`` target (default stdout).

See REVERSIBILITY.md. Off by default: nothing runs unless invoked. Read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# --- Tunable defaults (all overridable via CLI flags; no code change to tune) ---
DEFAULT_SHINGLE_K = 3          # k-line shingle window for Jaccard
DEFAULT_EXACT_N = 4            # min verbatim line-run shared across files
DEFAULT_HIGH_SIM = 0.40       # Jaccard >= this => high-similarity pair
DEFAULT_MIN_FILES = 2         # cluster must touch >= this many files to HOIST

# --- D-3: seeded label taxonomy (hint, not hardcode). Anchor regexes only. ---
# Each label: list of regexes; a normalized block hitting any => labeled.
LABELS: List[Tuple[str, List[str]]] = [
    ("blast-radius-taxonomy", [r"blast[\s\-]?radius", r"\bsev(erity)?\b.*\b(s0|s1|s2|s3)\b"]),
    ("definition-of-done-tdd", [r"definition of done", r"\bred[\s\-]?green[\s\-]?refactor\b",
                                r"\btests? (must|before) (pass|code)\b", r"\btdd\b"]),
    ("doc-share-invocation", [r"doc[\s\-]?share", r"share .*as .*(dark|web) link"]),
    ("daemon-deprecation-caveat", [r"daemon .*deprecat", r"dispatcher runs in the gateway"]),
]
_COMPILED_LABELS = [(name, [re.compile(p, re.IGNORECASE) for p in pats]) for name, pats in LABELS]

_BULLET_RE = re.compile(r"^([*\-+]|\d+[.)]|#{1,6})\s*")
_QUOTE_RE = re.compile(r"^>+\s*")
_INLINE_MD_RE = re.compile(r"[`*_]+")


# --------------------------------------------------------------------------- #
# Core analysis (pure functions -> deterministic).                            #
# --------------------------------------------------------------------------- #
def discover(skill_root: Path) -> List[Path]:
    """Return sorted prd-*/SKILL.md paths under ``skill_root`` (read-only glob)."""
    return sorted(skill_root.glob("prd-*/SKILL.md"), key=lambda p: str(p))


def normalize(text: str) -> List[str]:
    """Strip markdown bullets/inline syntax/whitespace, lowercase, drop blank lines."""
    out: List[str] = []
    for raw in text.splitlines():
        line = _QUOTE_RE.sub("", raw)
        line = _BULLET_RE.sub("", line)
        line = _INLINE_MD_RE.sub("", line)
        line = re.sub(r"\s+", " ", line).strip().lower()
        if line:
            out.append(line)
    return out


def _h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def shingles(lines: Sequence[str], k: int) -> set:
    """Hashed set of k-line windows over normalized lines."""
    if k <= 0:
        k = 1
    return {_h("\n".join(lines[i:i + k])) for i in range(0, max(0, len(lines) - k + 1))}


def pairwise_jaccard(file_shingles: Dict[str, set]) -> Dict[Tuple[str, str], float]:
    """Jaccard similarity for every unordered file pair (deterministic key order)."""
    keys = sorted(file_shingles)
    scores: Dict[Tuple[str, str], float] = {}
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            sa, sb = file_shingles[a], file_shingles[b]
            if not sa and not sb:
                continue
            inter = len(sa & sb)
            union = len(sa | sb)
            if union:
                scores[(a, b)] = inter / union
    return scores


def exact_blocks(file_lines: Dict[str, List[str]], n: int) -> List[Tuple[str, List[str], str]]:
    """Find verbatim >=n-line runs shared across >=2 files.

    Returns list of (block_hash, sorted_files, sample_text), sorted deterministically.
    """
    if n <= 0:
        n = 1
    block_files: Dict[str, set] = {}
    block_text: Dict[str, str] = {}
    for fname in sorted(file_lines):
        lines = file_lines[fname]
        for i in range(0, max(0, len(lines) - n + 1)):
            window = lines[i:i + n]
            key = _h("\u0001".join(window))
            block_files.setdefault(key, set()).add(fname)
            block_text.setdefault(key, " / ".join(window))
    result = []
    for key, files in block_files.items():
        if len(files) >= 2:
            result.append((key, sorted(files), block_text[key]))
    # Stable order: most files first, then by sample text, then hash.
    result.sort(key=lambda t: (-len(t[1]), t[2], t[0]))
    return result


def label(block_text: str) -> str:
    """Map a block to a known cross-cutting label, or 'unlabeled' (D-3)."""
    for name, pats in _COMPILED_LABELS:
        if any(p.search(block_text) for p in pats):
            return name
    return "unlabeled-candidate"


def recommend(label_name: str, n_files: int, sample: str,
              min_files: int, high_sim: float, sim: float) -> Tuple[str, str]:
    """D-4 heuristic: HOIST vs LEAVE with an explicit, fallible reason string."""
    is_policy = label_name not in ("unlabeled-candidate",)
    short_or_example = len(sample) < 24 or sample.startswith("`") or "e.g." in sample
    if n_files >= min_files and (is_policy or sim >= high_sim):
        if is_policy:
            return "HOIST", f"policy-label '{label_name}' duplicated across {n_files} files"
        return "HOIST", f"high-similarity ({sim:.2f}>={high_sim:.2f}) across {n_files} files"
    if n_files <= 1:
        return "LEAVE", "possible-cold-worker-context: appears in <=1 file"
    if short_or_example:
        return "LEAVE", "possible-cold-worker-context: short/example-like block"
    return "LEAVE", f"below threshold (sim={sim:.2f}<{high_sim:.2f}), not policy-labeled"


# --------------------------------------------------------------------------- #
# Cluster assembly + rendering.                                               #
# --------------------------------------------------------------------------- #
class Cluster:
    __slots__ = ("label", "files", "sample", "sim", "rec", "reason")

    def __init__(self, label: str, files: List[str], sample: str, sim: float,
                 rec: str, reason: str):
        self.label = label
        self.files = files
        self.sample = sample
        self.sim = sim
        self.rec = rec
        self.reason = reason


def _max_sim_for(files: List[str], scores: Dict[Tuple[str, str], float]) -> float:
    best = 0.0
    fs = sorted(files)
    for i in range(len(fs)):
        for j in range(i + 1, len(fs)):
            best = max(best, scores.get((fs[i], fs[j]), 0.0))
    return best


def analyze(skill_root: Path, k: int, n: int, high_sim: float,
            min_files: int) -> Tuple[List[str], Dict[Tuple[str, str], float], List[Cluster]]:
    paths = discover(skill_root)
    rels = [str(p.relative_to(skill_root)) for p in paths]
    file_lines: Dict[str, List[str]] = {}
    for p, rel in zip(paths, rels):
        file_lines[rel] = normalize(p.read_text(encoding="utf-8", errors="replace"))
    file_shingles = {rel: shingles(lines, k) for rel, lines in file_lines.items()}
    scores = pairwise_jaccard(file_shingles)

    clusters: List[Cluster] = []
    seen_keys = set()
    for _key, files, sample in exact_blocks(file_lines, n):
        lab = label(sample)
        sim = _max_sim_for(files, scores)
        rec, reason = recommend(lab, len(files), sample, min_files, high_sim, sim)
        sig = (lab, tuple(files), rec)
        if sig in seen_keys:
            continue
        seen_keys.add(sig)
        clusters.append(Cluster(lab, files, sample, sim, rec, reason))

    # Deterministic cluster order.
    clusters.sort(key=lambda c: (c.rec != "HOIST", c.label, -len(c.files),
                                 tuple(c.files), c.sample))
    return rels, scores, clusters


def render_map(skill_root: Path, rels: List[str],
               scores: Dict[Tuple[str, str], float],
               clusters: List[Cluster], high_sim: float) -> str:
    lines: List[str] = []
    lines.append("# prd_dry_audit — Cross-Skill Duplication Map")
    lines.append("")
    lines.append("_Read-only artifact. This tool reports; it does not rewrite skills._")
    lines.append("")
    lines.append("## Scanned files")
    if rels:
        for r in rels:
            lines.append(f"- {r}")
    else:
        lines.append("- (none found)")
    lines.append("")
    lines.append("## High-similarity file pairs")
    hi = sorted(((s, a, b) for (a, b), s in scores.items() if s >= high_sim),
                key=lambda t: (-t[0], t[1], t[2]))
    if hi:
        for s, a, b in hi:
            lines.append(f"- {a}  <->  {b}  (jaccard={s:.3f})")
    else:
        lines.append("- (none above threshold)")
    lines.append("")
    lines.append("## Duplication clusters")
    if not clusters:
        lines.append("- (no shared verbatim blocks found)")
    for c in clusters:
        lines.append("")
        lines.append(f"### [{c.rec}] {c.label}")
        lines.append(f"- files ({len(c.files)}): {', '.join(c.files)}")
        lines.append(f"- max-pair-jaccard: {c.sim:.3f}")
        lines.append(f"- reason: {c.reason}")
        lines.append(f"- sample: {c.sample}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Self-check fixture (bundled, in-memory; writes only to a temp dir it owns).  #
# --------------------------------------------------------------------------- #
# Shared cross-cutting blocks (>=4 verbatim normalized lines each) so each rule
# forms its own detectable cluster; file-unique filler keeps the blocks separate.
_BLOCK_BLAST_RADIUS = (
    "## blast radius\n"
    "classify the blast radius severity.\n"
    "s0 trivial, s1 local change.\n"
    "s2 module-wide, s3 fleet-wide.\n"
    "escalate s3 to a human before proceeding.\n"
)
_BLOCK_DOD = (
    "## definition of done\n"
    "definition of done: tests before code.\n"
    "follow red-green-refactor strictly.\n"
    "tdd is enforced; no merge without green.\n"
    "paste the real verify output into handoff.\n"
)
_BLOCK_DOC_SHARE = (
    "## doc-share\n"
    "share the artifact via doc-share.\n"
    "render it as a dark-mode web link.\n"
    "post the doc-share link into chat.\n"
    "never paste raw html into the channel.\n"
)
_FIXTURE: Dict[str, str] = {
    "prd-alpha/SKILL.md": (
        "# prd-alpha\n"
        "alpha unique interview guidance here.\n"
        + _BLOCK_BLAST_RADIUS
        + "alpha tail filler one two three.\n"
        + _BLOCK_DOD
        + "alpha closing unique note.\n"
        + _BLOCK_DOC_SHARE
    ),
    "prd-beta/SKILL.md": (
        "# prd-beta\n"
        "beta unique fanout notes here.\n"
        + _BLOCK_BLAST_RADIUS
        + "beta tail filler nine eight seven.\n"
        + _BLOCK_DOD
        + "beta closing unique note.\n"
        + _BLOCK_DOC_SHARE
    ),
    "prd-gamma/SKILL.md": (
        "# prd-gamma\n"
        "gamma cold-worker context line.\n"
        + _BLOCK_DOD
        + "gamma middle unique filler.\n"
        "caveat: the daemon is deprecated; the dispatcher runs in the gateway now.\n"
        "gamma trailing unique guidance.\n"
    ),
}


def _materialize_fixture(base: Path) -> Path:
    root = base / "fixture_skills"
    for rel, body in _FIXTURE.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def selfcheck(verbose: bool = False) -> int:
    """Health probe: 0 on known-good fixture, non-zero otherwise. Owns its temp dir."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="prd_dry_audit_selfcheck_") as td:
        root = _materialize_fixture(Path(td))
        rels, scores, clusters = analyze(root, DEFAULT_SHINGLE_K, DEFAULT_EXACT_N,
                                         DEFAULT_HIGH_SIM, DEFAULT_MIN_FILES)
        labels_found = {c.label for c in clusters}
        hoists = {c.label for c in clusters if c.rec == "HOIST"}
        # Determinism: re-render twice, bytes must match.
        m1 = render_map(root, rels, scores, clusters, DEFAULT_HIGH_SIM)
        rels2, scores2, clusters2 = analyze(root, DEFAULT_SHINGLE_K, DEFAULT_EXACT_N,
                                            DEFAULT_HIGH_SIM, DEFAULT_MIN_FILES)
        m2 = render_map(root, rels2, scores2, clusters2, DEFAULT_HIGH_SIM)

        checks = {
            "discovered_3_files": len(rels) == 3,
            "deterministic": m1 == m2,
            "blast_radius_labeled": "blast-radius-taxonomy" in labels_found,
            "dod_labeled": "definition-of-done-tdd" in labels_found,
            "doc_share_labeled": "doc-share-invocation" in labels_found,
            "dod_hoisted": "definition-of-done-tdd" in hoists,
            # daemon caveat appears in exactly ONE file -> must NOT be a shared cluster.
            "daemon_not_clustered": "daemon-deprecation-caveat" not in labels_found,
        }
        ok = all(checks.values())
        if verbose or not ok:
            for name, passed in sorted(checks.items()):
                print(f"  [{'ok' if passed else 'FAIL'}] {name}", file=sys.stderr)
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# CLI.                                                                         #
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prd_dry_audit",
        description="Read-only cross-skill DRY duplication mapper for prd-* SKILL.md files.",
    )
    p.add_argument("--root", type=Path, default=None,
                   help="Skill root containing prd-*/SKILL.md dirs.")
    p.add_argument("--out", type=Path, default=None,
                   help="Output file for the map (default: stdout).")
    p.add_argument("--shingle-k", type=int, default=DEFAULT_SHINGLE_K,
                   help=f"k-line shingle window (default {DEFAULT_SHINGLE_K}).")
    p.add_argument("--exact-n", type=int, default=DEFAULT_EXACT_N,
                   help=f"min verbatim line-run shared across files (default {DEFAULT_EXACT_N}).")
    p.add_argument("--high-sim", type=float, default=DEFAULT_HIGH_SIM,
                   help=f"Jaccard high-similarity threshold (default {DEFAULT_HIGH_SIM}).")
    p.add_argument("--min-files", type=int, default=DEFAULT_MIN_FILES,
                   help=f"min files for a HOIST recommendation (default {DEFAULT_MIN_FILES}).")
    p.add_argument("--selfcheck", action="store_true",
                   help="Run health probe over bundled fixture; exit 0 good / non-zero bad.")
    p.add_argument("--verbose", action="store_true", help="Verbose selfcheck output.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selfcheck:
        return selfcheck(verbose=args.verbose)
    if args.root is None:
        print("error: --root is required (or use --selfcheck)", file=sys.stderr)
        return 2
    root = args.root
    if not root.is_dir():
        print(f"error: --root not a directory: {root}", file=sys.stderr)
        return 2
    rels, scores, clusters = analyze(root, args.shingle_k, args.exact_n,
                                     args.high_sim, args.min_files)
    text = render_map(root, rels, scores, clusters, args.high_sim)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
