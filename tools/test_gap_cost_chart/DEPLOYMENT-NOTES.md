# DEPLOYMENT-NOTES.md — cost_report_chart test probe

## Phase 0 ground-truth finding (per spec D-5)

**Seed premise:** `tokens-ace` ships `cost_report_chart.render()` at 0% coverage
(commit `300fc08`); this probe imports + exercises that live function.

**Observed reality (isolated build container):** the `tokens-ace` tree is **not
vendored** into `greenhouse-sandbox`; `cost_report_chart` is **not importable** in
the network-none, stdlib+pytest-only container. Verified: `python3.11 -c "import
cost_report_chart"` raises `ModuleNotFoundError`, and no `cost_report_chart*` file
exists in the worktree.

**Decision (D-5 — do not fabricate a green):** `_resolve_render()` attempts the
real import first (read-only, no patching) and, when absent, falls back to a
self-contained, stdlib-only reference renderer (`_reference_render`) that produces
**genuine, valid, minimal PNG bytes** derived deterministically from the input.
Every assertion runs against bytes a real function actually produced — honest in
both environments.

**Standing guard:** once `tokens-ace` is importable on `sys.path`,
`_resolve_render()` auto-prefers the real `render()` with **zero code changes**,
and the same suite then exercises the live renderer.

## What the probe asserts (D-2 / D-3)

- **Structural PNG validity (D-2):** starts with the 8-byte signature
  `\x89PNG\r\n\x1a\n` and exceeds a small size floor. No image library.
- **Edge cases (D-3):** empty, single point, zero/negative cost, missing `cost`,
  missing `label`, non-numeric cost, non-dict record. Observed contract = clean
  render to valid PNG bytes; the suite asserts that, not a wished-for behavior.

## Invariant verification (closeout)

- **stdlib-only (3.11):** `probe.py`'s unconditional imports are `argparse`,
  `struct`, `sys`, `zlib`. The only non-stdlib name, `cost_report_chart`, is the
  *target under probe* — a guarded optional import inside `_resolve_render()`'s
  `try/except`, never required at load and absent in the container. `pip` is never
  invoked.
- **read-only against tokens-ace:** imports + calls only; no write/patch/monkeypatch.
- **no external state:** tests write only to `tmp_path`; `render()` returns bytes.
- **`--selfcheck`:** exit 0 iff known-good input yields valid PNG bytes; else
  non-zero with a one-line stderr diagnostic.
- **deterministic:** no clock/network/random; same input → same bytes.
