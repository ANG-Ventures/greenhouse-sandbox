# branch_janitor — Reversibility

`branch_janitor` is a **read-only triage reporter**. It exists to make stale-branch
cleanup *legible*, not to perform it. Rolling it back is trivial because it changes
no repository or remote state.

## Reversibility

- **Off by default.** The tool does nothing unless explicitly invoked
  (`python -m tools.branch_janitor ...`). It ships no cron job, no launchd/systemd
  unit, no scheduler, and no daemon. It never runs on its own.
- **Read-only by construction.** It enumerates branches/PR states from a JSON
  snapshot (or read-only `git`/`gh` queries) and emits a report. It contains **no**
  branch-, remote-, or PR-mutating call. It never deletes, pushes, merges, or rebases.
- **The delete script is inert.** With `--out PATH` the tool writes
  `branch_janitor_delete.sh`, but **every line in that script is commented out**
  (`# git push origin --delete <name>`). As shipped it deletes nothing. A human must
  read it, uncomment specific lines, and run them deliberately. Deletion is fully
  human-gated opt-in.
- **State it touches.** Only the paths you pass: it writes the report to **stdout**
  and (optionally) the inert script to the **`--out`** path you choose. It reads the
  `--input` JSON (or stdin). It touches no global config, no env, no home directory,
  no network writes.
- **Uninstall / roll back.** Delete the two files:
  `tools/branch_janitor.py` and `tests/test_branch_janitor.py`. Nothing else was
  installed. Any report or `--out` script you generated is a plain file you can
  delete; removing it restores the prior state exactly (no branches were affected).
- **Deploy health probe.** `python -m tools.branch_janitor --selfcheck` returns `0`
  on known-good input and non-zero otherwise; it mutates nothing, so re-running or
  rolling back is safe at any time.

---

# cost_report_chart test probe — Reversibility

Read-only smoke + edge-case probe + `--selfcheck` health CLI for
`cost_report_chart.render()`. Authoritative copy:
`tools/test_gap_cost_chart/REVERSIBILITY.md`.

## Reversibility

- **Off by default.** Runs only when explicitly invoked (`pytest
  tests/test_cost_report_chart.py` or `python -m tools.test_gap_cost_chart.probe
  --selfcheck`). No plugin, hook, cron, unit, or daemon.
- **Read-only.** Imports + calls `cost_report_chart.render()` only; never mutates
  `tokens-ace`. Stdlib reference renderer when the real module is absent.
- **State touched.** None outside its files; bytes in-memory, tests use `tmp_path`.
- **Uninstall.** Delete `tools/test_gap_cost_chart/` and
  `tests/test_cost_report_chart.py`; restores prior state exactly.

---

# skillcov — Reversibility

`skillcov` is a **read-only static audit** that walks a skills directory tree and
emits a coverage map (Markdown + optional JSON). It never modifies, creates,
executes, or backfills any skill it scans — it only computes and reports.

## Reversibility

- **Off by default.** The tool does nothing unless explicitly invoked
  (`python -m tools.skillcov --root ... --out ...`). It ships no cron job, no
  launchd/systemd unit, no scheduler, hook, or daemon. It never runs on its own.
- **Read-only over the scanned tree.** It opens skill files read-only and writes
  ONLY to the single `--out` path you pass (and `<out>.json` when `--json` is
  set). It never writes inside the scanned skills root. With no `--out`, it writes
  the report to **stdout** only. Symlinks in the tree are not followed (no escape).
- **No execution of scanned content.** Classification is by static inspection
  only — file presence, glob, and frontmatter line-scanning. It never imports,
  `exec`s, or subprocesses any discovered file. Scanned skills are treated as
  untrusted data, not code.
- **State it touches.** Only the `--out` path you choose (default under
  `tools/skillcov/`). It touches no global config, no env, no home directory, and
  makes no network calls. The report/JSON it writes are plain files.
- **Uninstall / roll back.** Delete two files:
  `tools/skillcov.py` and `tests/test_skillcov.py`. Nothing else was installed.
  Any report or JSON sidecar you generated is a plain file; deleting it restores
  the prior state exactly (no skill was ever altered).
- **Deploy health probe.** `python -m tools.skillcov --selfcheck` returns `0` on a
  known-good in-memory fixture and non-zero otherwise. It builds its fixture in a
  temp dir it cleans up, mutates nothing else, so re-running or rolling back is
  safe at any time.
