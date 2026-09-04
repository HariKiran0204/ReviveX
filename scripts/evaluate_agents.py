"""CLI entry that does not require PYTHONPATH to already include packages/domain."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for name in ("eval", "db", "providers", "domain"):
    path = str(ROOT / "packages" / name)
    if path not in sys.path:
        sys.path.insert(0, path)

from recoverai_domain.agents.evaluation import run_agent_evaluation
from recoverai_domain.agents.quality import quality_gates


def main() -> None:
    report = run_agent_evaluation()
    gates = quality_gates()
    print(report)
    print(gates)
    if not all(gates.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
