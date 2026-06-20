"""Pytest root anchor.

Ensures the worktree root is on sys.path so ``from tools.<module> import ...``
resolves without importlib spec/exec_module hacks, even when tests/ is a package.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
