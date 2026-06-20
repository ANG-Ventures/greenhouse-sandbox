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

# docs_ace_index — Reversibility

`docs_ace_index` is a **pure static-site renderer**. It reads a hand-maintained
TOML manifest and emits one self-contained dark-mode `index.html`. It probes
nothing, serves nothing, and runs on its own never.

## Reversibility

- **Off by default.** Does nothing unless explicitly invoked
  (`python -m tools.docs_ace_index build` or `... --selfcheck`). Ships no cron
  job, no launchd/systemd unit, no scheduler, no daemon, no server. It never
  runs on its own.
- **No network, ever.** Stdlib-only (`tomllib`, `html`, `argparse`, `pathlib`,
  `sys`, `datetime`). It imports no `socket`, `urllib`, or `http.client`. The
  listed URLs are rendered as inert text/links; v0.1 never fetches them.
- **State it touches.** It reads `tools/docs_ace_index/manifest.toml` (or a
  `--manifest` path) and writes one HTML file to the `--out` path (default
  `index.html` beside the manifest). `--selfcheck` writes nothing. It touches no
  global config, no env, no home directory, no network.
- **Manifest is the trust boundary.** Every field is HTML-escaped before
  insertion; a stray `<script>` in an entry renders as inert escaped text.
- **Uninstall / roll back.** Delete the package dir
  `tools/docs_ace_index/` and the suite `tests/test_docs_ace_index.py`. Nothing
  else was installed. Any generated `index.html` is a plain file you can remove;
  deleting it restores the prior state exactly.
- **Deploy health probe.** `python -m tools.docs_ace_index --selfcheck` returns
  `0` on the bundled `fixtures/known_good.toml` and non-zero on any failure
  (corrupt/missing fixture). It mutates nothing, so re-running or rolling back is
  safe at any time.
