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
