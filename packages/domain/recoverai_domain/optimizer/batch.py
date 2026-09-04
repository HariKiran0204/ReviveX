from __future__ import annotations

from collections.abc import Sequence

from recoverai_domain.optimizer.service import RecoveryOptimizer
from recoverai_domain.optimizer.types import (
    BatchOptimizationResult,
    OptimizationResult,
    OptimizerCaseInput,
)


def optimize_batch(
    cases: Sequence[tuple[OptimizerCaseInput, dict[str, float] | None]],
    *,
    optimizer: RecoveryOptimizer | None = None,
) -> BatchOptimizationResult:
    """Score and rank legal actions for many cases. Does not execute interventions."""
    engine = optimizer or RecoveryOptimizer()
    results: list[OptimizationResult] = []
    for snapshot, probabilities in cases:
        results.append(engine.optimize(snapshot, probabilities=probabilities))
    return BatchOptimizationResult(
        optimizer_version=engine.settings.optimizer_version,
        results=tuple(results),
    )
