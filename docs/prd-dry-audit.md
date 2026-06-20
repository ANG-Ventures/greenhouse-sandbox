# PRD — `prd_dry_audit`: Cross-skill DRY duplication map for the prd-* suite

**Status:** Draft v0.1 (Greenhouse nightly autonomous build) · **Target repo:** `greenhouse-sandbox` (`tools/prd_dry_audit.py` + `tests/test_prd_dry_audit.py`) · **Stack:** stdlib-only Python 3.11 · **Blast radius:** zero (sandbox; never writes outside its own files)

---

## 1. Summary & Goal

The 10 real prd-* skills (~3,061 SKILL.md lines; "11" counts the `prd-swarm-planner` rename stub) re-inline the same cross-cutting rules, and those copies silently drift: the "daemon deprecated — dispatcher runs in the gateway" caveat lives in exactly **one** skill (`prd-swarm-plan`), so when that fact changed only one copy got patched and the rest would have drifted had they carried it. Every cross-cutting rule has that failure mode.

`prd_dry_audit` is a single stdlib-only Python tool that **scans the prd-* SKILL.md files, finds recurring near-duplicate text blocks across skills, clusters them, and emits a ranked duplication map** to stdout (text) or JSON. It is a **read-only reporting tool**: it produces the de-risking artifact the human uses to decide what to hoist into a shared `_prd-common/` — it does **not** edit, hoist, or move any skill text itself. The judgment ("drift-prone policy → hoist" vs. "load-bearing context a cold worker needs inline → leave") stays with the human; the tool supplies the evidence (which blocks repeat, where, and how similar) that makes that judgment fast and mechanical.

## 2. Non-Goals

- **Does not edit, rewrite, hoist, or delete any skill file.** No `_prd-common/` is created by the tool. Output is a report only.
- **Does not decide hoist-vs-leave.** It ranks and flags candidates; the human chooses.
- **Not a general dedup engine.** Scope is the prd-* SKILL.md files in one skills dir, nothing else.
- **No network, no third-party deps, no persistent state.** stdlib only.

## 3. Constitution / Invariants

- **Invariant — read-only.** The tool opens skill files for reading only and writes nothing outside its own stdout/stderr (and the optional `--out <path>` report file the user names).
  - *Why:* it audits the canonical skills suite; a stray write could corrupt a live skill.
  - *Closeout proof:* `test_no_writes_to_scanned_dir` — run against a temp fixture tree, assert mtimes and dir listing are byte-identical before/after; `grep` shows no `open(..., 'w')`/`write_text` over any path under the scan root.
- **Invariant — stdlib-only / 3.11.** No imports outside the Python 3.11 standard library.
  - *Closeout proof:* `test_imports_are_stdlib_only` parses the module AST and asserts every import root is in `sys.stdlib_module_names`.
- **Invariant — deterministic.** Same input tree → byte-identical report (stable cluster + skill ordering; no wall-clock, no PRNG, no dict-iteration-order leakage).
  - *Closeout proof:* `test_deterministic` runs the audit twice on the same fixture, asserts equal output.

## 4. Resolved Decisions

- **D-1 — Report, don't hoist.** The de-risking artifact named in the seed *is* the duplication map. Auto-hoisting is out of scope.
- **D-2 — Block unit = paragraph.** A "block" is a paragraph (text run between blank lines), with list bullets joined to their lead-in.
- **D-3 — Similarity = normalized-token Jaccard with a default 0.80 threshold.** Normalize a block by lowercasing, stripping markdown punctuation/backticks/links, and collapsing whitespace; compare token sets by Jaccard.
- **D-4 — A cluster is cross-skill or it's dropped.** A duplication cluster only matters if it spans **≥2 distinct skills**.
- **D-5 — Hoist signal is advisory, never a decision.** Each cluster prints a `signal`: `HOIST?` (policy-shaped: many skills, high similarity) vs. `LEAVE?` (few skills, lower similarity). A sort hint with a printed rationale — the human decides.
- **D-6 — Scan root is a CLI arg, default to the live skills dir.** Default `--root /Users/alexgierczyk/.hermes/skills-shared/general`; overridable so tests run on a fixture tree.

## 5. Architecture / Design

Single module `tools/prd_dry_audit.py`:

1. **Discover** — glob `<root>/prd-*/SKILL.md`, skip dirs whose SKILL.md is a rename stub (`RENAMED → load`); record `skill_name → text`.
2. **Blockify + normalize** — split each skill into paragraph blocks; for each, keep `raw`, `normalized` token set, and `(skill, ordinal)` provenance.
3. **Cluster** — single-link cluster blocks across skills by Jaccard ≥ threshold; keep only clusters spanning ≥2 distinct skills (D-4).
4. **Rank + signal** — sort clusters by (distinct-skill count desc, mean-similarity desc); attach the D-5 advisory signal + a one-line rationale.
5. **Emit** — text table (default) or `--json`; one row per cluster.

## 6. CLI

```
prd_dry_audit.py [--root DIR] [--threshold F] [--min-skills N] [--json] [--out PATH] [--selfcheck]
```

- `--selfcheck` runs the audit against a built-in known-good fixture and exits 0 iff the expected cluster is found (deploy health probe).

## 7. Reversibility

See `REVERSIBILITY.md`. Off by default, read-only, no external state; deletable in one `rm`.
