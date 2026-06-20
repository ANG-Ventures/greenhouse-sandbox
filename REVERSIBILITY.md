# prd_dry_audit — Reversibility

## Reversibility

**Off by default.** `prd_dry_audit` is a manually-invoked CLI tool. Nothing runs it
automatically — there is no cron job, no launchd unit, no import hook, no gateway
wiring. If you never call `python tools/prd_dry_audit.py`, it does nothing.

**Read-only by construction.** The tool opens skill files with `read_text(...)` only.
The sole write paths are (a) stdout and (b) the optional `--out <path>` report file
that *you* name. It never writes, edits, hoists, moves, or deletes any skill file, and
it creates no `_prd-common/` directory. Running the audit against the live skills dir
leaves that tree byte-identical (covered by `test_no_writes_to_scanned_dir`).

**No external or persistent state.** No database, cache, config file, env var, network
call, or third-party dependency. stdlib-only Python 3.11. Each run is a pure function of
the input tree plus CLI flags.

## Uninstall / roll back

There is nothing to "uninstall." To remove the tool entirely:

```
rm tools/prd_dry_audit.py tests/test_prd_dry_audit.py docs/prd-dry-audit.md
rm REVERSIBILITY.md tools/__init__.py   # if not shared with other sandbox tools
```

Delete any report files you generated with `--out`. No other state exists to clean up,
and no system behaviour changes when the files are gone.

## State touched

| State | Touched? |
|-------|----------|
| Skill files under `--root` | Read-only |
| Filesystem outside `--out` | Never |
| Network | Never |
| Persistent config / cache / db | None |
| Background schedulers (cron/launchd) | None |
