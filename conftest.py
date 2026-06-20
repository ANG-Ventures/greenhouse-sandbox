"""Pytest bootstrap: put the worktree root on sys.path so `from tools.* import ...`
resolves when pytest is invoked from anywhere. No importlib spec/exec_module."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
