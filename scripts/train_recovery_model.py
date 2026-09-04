"""CLI entry that does not require PYTHONPATH to already include packages/eval."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for name in ("eval", "db", "providers", "domain"):
    path = str(ROOT / "packages" / name)
    if path not in sys.path:
        sys.path.insert(0, path)

from recoverai_eval.train import main

if __name__ == "__main__":
    main()
