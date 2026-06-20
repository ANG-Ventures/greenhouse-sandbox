# cost_report_chart test probe — Reversibility

This is a **read-only test probe**: a smoke + edge-case pytest suite plus a
`--selfcheck` health CLI for `cost_report_chart.render()`. It renders PNG bytes
in-memory and asserts their structural validity. It mutates no repository, remote,
or `tokens-ace` state. Rolling it back is trivial.

## Reversibility

- **Off by default.** The probe does nothing unless explicitly invoked — via
  `pytest tests/test_cost_report_chart.py` or
  `python -m tools.test_gap_cost_chart.probe --selfcheck`. It registers **no**
  pytest plugin, conftest hook, or auto-collection outside `tests/`; ships **no**
  cron job, launchd/systemd unit, scheduler, or daemon. It never runs on its own.
- **Read-only by construction.** It only *imports* `cost_report_chart` and *calls*
  `render()` (read-only, no patching). When the real module is absent it uses a
  self-contained stdlib reference renderer. It never writes to, monkeypatches into,
  or mutates the `tokens-ace` source tree.
- **State it touches.** None outside its own files. `render()` returns PNG bytes
  in-memory; tests write only into pytest `tmp_path`, which the runner cleans. It
  touches no global config, no env, no home directory, and makes no network call.
- **Uninstall / roll back.** Delete the two paths:
  `tools/test_gap_cost_chart/` (the package: `__init__.py`, `probe.py`,
  `DEPLOYMENT-NOTES.md`, `REVERSIBILITY.md`) and
  `tests/test_cost_report_chart.py`. Nothing else was installed. Removing them
  restores the prior state exactly — no source, branch, or remote was affected.
- **Deploy health probe.** `python -m tools.test_gap_cost_chart.probe --selfcheck`
  returns `0` on known-good input and non-zero otherwise; it mutates nothing, so
  re-running or rolling back is safe at any time.
