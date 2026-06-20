# branch-triage

## Reversibility

- **Off by default.** `branch-triage` is a read-only analyzer. It performs **no**
  repository or remote mutation in any mode. It never runs `git branch -D`,
  `git push`, `git update-ref`, `git commit`, or any other write — every git call
  goes through a single `_run_git()` chokepoint with a read-only allow-list
  (`for-each-ref`, `merge-base`, `rev-parse`, `log`); any write verb raises
  `WriteVerbError` before exec. The proposed-cleanup block is **inert text** a
  human copies and runs manually; nothing happens to the fork otherwise.

- **No state outside its own files.** No DB, no dotfile, no cache, no env writes,
  no network, no GitHub API, no auth token. Its entire footprint is:
  - `tools/branch_triage.py`
  - `tests/test_branch_triage.py`
  - `tests/fixtures/selfcheck_refs.txt`
  - `tests/fixtures/selfcheck_expected.txt`

- **Health probe.** `python tools/branch_triage.py --selfcheck; echo $?` renders
  the report over the committed fixture and compares it byte-for-byte to the
  committed expected output. Exit `0` = healthy; non-zero = drift. The nightly
  wrapper runs this before trusting any report.

## Uninstall / roll back

Delete the four files listed above. Removal leaves zero residue and cannot have
changed the fork (the tool never mutated it). There is no service, cron, or
launchd unit to disable — cadence is the caller's job, not the tool's.
