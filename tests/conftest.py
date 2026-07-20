"""
Ensure the repo root is importable as `app.*` when running via the
pytest.exe entrypoint. Appended (not inserted at index 0) so the
top-level `cmd/` package here doesn't shadow the stdlib `cmd` module
that pytest's own --pdb support needs.
"""
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.append(ROOT)
