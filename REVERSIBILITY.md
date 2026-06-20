# prd_dry_audit — Reversibility

## Reversibility

**Off by default.** `prd_dry_audit` is a passive, read-only CLI tool. Nothing runs,
schedules, installs, or persists unless a human explicitly invokes
`tools/prd_dry_audit.py`. There is no daemon, no cron entry, no import side effect,
no auto-registration.

### What state it touches
- **Inputs:** opens `prd-*/SKILL.md` files under `--root` **for read only**. It never
  writes, renames, moves, or deletes any skill file or `references/` dir. (Verified by
  `test_no_writes_outside_own_output`, which hashes the input tree before/after.)
- **Outputs:** writes exactly one file when `--out PATH` is given; otherwise prints the
  map to stdout and writes nothing. No caches, dotfiles, temp state, or `_prd-common/`
  directory are created. `--selfcheck` materializes a fixture only inside a
  `tempfile.TemporaryDirectory` it owns and auto-deletes. (Verified by
  `test_selfcheck_creates_no_side_files`.)

### How to uninstall / roll back
1. The tool is self-contained in `tools/prd_dry_audit.py` (+ `tools/__init__.py`).
   Delete those files to remove it; no other path is affected.
2. If you ran it with `--out PATH`, delete that one output file. That is the only
   artifact it can create.
3. There is nothing else to undo — no config, no registry, no scheduled job, no
   modification to any skill. Removing the files fully reverses the build.

### Health probe
`python tools/prd_dry_audit.py --selfcheck` exits **0** on the bundled known-good
fixture and **non-zero** if the analysis contract regresses. Use it as the deploy
health check; it touches no real skill files.
