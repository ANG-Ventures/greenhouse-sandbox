# fork-branch-hygiene

## Reversibility

- **Off by default.** The tool does nothing unless explicitly invoked. It ships no
  cron/launchd/systemd unit, no daemon, no persistent state, and is not wired into
  any automation. Running it requires a deliberate human command.
- **Read-only by construction.** It performs no deletion, no `git push`, and no git
  ref mutation of any kind. It spawns no subprocess, opens no socket, and makes no
  network call. Input is *fed* (stdin or a file), not fetched. The only thing it
  can write is its own report: stdout, and — only when you pass `--out PATH` — that
  one named file. It touches no global config and no repository state.
- **State touched / roll back.** None outside an explicit `--out` file; with no
  `--out`, output is stdout only and the filesystem is untouched. The tool only
  classifies/reports, so there is nothing to undo in the fork — to discard a report,
  delete the `--out` file you named (if any). No other artifact exists.
- **Uninstall.** Delete `tools/fork_branch_hygiene.py` and
  `tests/test_fork_branch_hygiene.py`. Deploy rollback is the atomic-swap restore of
  the prior bytes from the deploy slot's `previous` snapshot.
- **Deploy health probe.** `python3.11 tools/fork_branch_hygiene.py --selfcheck`
  prints `selfcheck: OK` and exits `0` on a known-good in-memory fixture; any drift
  prints a diff to stderr and exits `1`.
