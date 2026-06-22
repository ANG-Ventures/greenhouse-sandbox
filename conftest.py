import os
import sys

# Put the worktree root on sys.path so `from tools.<module> import ...` works
# under `python -m pytest -q` with no editable install or extra wiring.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
