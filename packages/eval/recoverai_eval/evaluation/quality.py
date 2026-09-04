from __future__ import annotations

from typing import Any

from recoverai_eval.constants import LEAKAGE_FIELDS, MODEL_FEATURE_COLUMNS
from recoverai_eval.errors import ModelQualityError


def run_quality_gates(
    *,
    y_true: list[int],
    y_prob: list[float],
    metrics: dict[str, Any],
    calibration: dict[str, Any],
    train_case_ids: set[str],
    test_case_ids: set[str],
    feature_names: list[str],
) -> dict[str, Any]:
    failures: list[str] = []
    if any(p < 0.0 or p > 1.0 for p in y_prob):
        failures.append("probabilities_outside_unit_interval")
    roc = metrics.get("roc_auc")
    pr = metrics.get("pr_auc")
    brier = metrics.get("brier")
    if roc != roc or pr != pr or brier != brier:  # NaN
        failures.append("metrics_nan")
    if isinstance(roc, float) and roc < 0.60:
        failures.append("roc_auc_below_0.60")
    if isinstance(pr, float) and pr < 0.20:
        failures.append("pr_auc_below_0.20")
    if isinstance(brier, float) and brier > 0.25:
        failures.append("brier_above_0.25")
    ece = float(calibration.get("ece") or 0.0)
    if ece > 0.12:
        failures.append("calibration_ece_above_0.12")
    if train_case_ids & test_case_ids:
        failures.append("train_test_case_overlap")
    leaked_features = set(feature_names) & LEAKAGE_FIELDS
    if leaked_features:
        failures.append(f"feature_leakage:{sorted(leaked_features)}")
    unexpected = [name for name in feature_names if name not in MODEL_FEATURE_COLUMNS]
    if unexpected:
        failures.append(f"unknown_features:{unexpected}")
    if sum(y_true) == 0 or sum(y_true) == len(y_true):
        failures.append("degenerate_test_labels")
    passed = not failures
    result = {"passed": passed, "failures": failures, "ece": ece}
    if not passed:
        raise ModelQualityError("QUALITY_GATE", f"Model failed quality gates: {failures}")
    return result
