from __future__ import annotations

import ast
from pathlib import Path

from recoverai_domain.agents.evaluation import run_agent_evaluation

_AGENTS_ROOT = Path(__file__).resolve().parent
_FORBIDDEN_IMPORTS = frozenset({"recoverai_providers"})
_FORBIDDEN_NAMES = frozenset({"PaymentProvider", "amount_recovered"})


def agent_source_files() -> list[Path]:
    return [path for path in _AGENTS_ROOT.rglob("*.py") if path.name != "__pycache__"]


def scan_agent_safety() -> dict[str, bool]:
    provider_import = False
    recovered_assign = False
    for path in agent_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in _FORBIDDEN_IMPORTS:
                        provider_import = True
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in _FORBIDDEN_IMPORTS:
                    provider_import = True
            if isinstance(node, ast.Attribute) and node.attr == "amount_recovered":
                parent_fields = getattr(node, "ctx", None)
                if isinstance(parent_fields, ast.Store):
                    recovered_assign = True
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "amount_recovered":
                        recovered_assign = True
    return {
        "no_provider_import": not provider_import,
        "no_recovered_assignment": not recovered_assign,
    }


def quality_gates() -> dict[str, bool]:
    eval_result = run_agent_evaluation()
    safety = scan_agent_safety()
    gates = dict(eval_result["gates"])
    gates.update(safety)
    gates["evaluation_complete"] = eval_result["completion_rate"] == 1.0
    return gates
