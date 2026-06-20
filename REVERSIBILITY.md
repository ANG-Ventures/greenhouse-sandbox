# Reversibility

- **Off by default:** this tool does nothing unless explicitly invoked; it ships no cron/launchd/service.
- **No external state:** writes nothing outside its own `--out`/stdout; touches no global config.
- **Uninstall / roll back:** delete `tools/greenpath_proof.py` and `tests/test_greenpath_proof.py`.
  Deploy rollback is the atomic-swap: `deployed/greenpath_proof/previous` restores the prior bytes.
