from __future__ import annotations

from typing import Any

from recoverai_eval.errors import ModelQualityError


def classification_metrics(
    y_true: list[int], y_prob: list[float], *, threshold: float = 0.5
) -> dict[str, Any]:
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        confusion_matrix,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    if not y_true or not y_prob:
        raise ModelQualityError("INVALID_METRICS", "Empty evaluation arrays")
    if any(p < 0.0 or p > 1.0 for p in y_prob):
        raise ModelQualityError("INVALID_PROBABILITY", "Predicted probability outside [0, 1]")
    y_hat = [1 if p >= threshold else 0 for p in y_prob]
    positives = sum(y_true)
    negatives = len(y_true) - positives
    roc = float("nan")
    pr = float("nan")
    if positives and negatives:
        roc = float(roc_auc_score(y_true, y_prob))
        pr = float(average_precision_score(y_true, y_prob))
    elif positives:
        pr = float(average_precision_score(y_true, y_prob))
    matrix = confusion_matrix(y_true, y_hat, labels=[0, 1]).tolist()
    return {
        "roc_auc": roc,
        "pr_auc": pr,
        "brier": float(brier_score_loss(y_true, y_prob)),
        "precision": float(precision_score(y_true, y_hat, zero_division=0)),
        "recall": float(recall_score(y_true, y_hat, zero_division=0)),
        "positive_rate": positives / len(y_true),
        "threshold": threshold,
        "confusion_matrix": {
            "labels": [0, 1],
            "matrix": matrix,
        },
        "n": len(y_true),
    }


def calibration_curve_points(
    y_true: list[int],
    y_prob: list[float],
    *,
    n_bins: int = 10,
) -> dict[str, Any]:
    bins: list[dict[str, float | int]] = []
    width = 1.0 / n_bins
    ece = 0.0
    total = len(y_true)
    max_abs = 0.0
    for index in range(n_bins):
        lo = index * width
        hi = 1.0 if index == n_bins - 1 else (index + 1) * width
        chosen = [
            (yt, yp)
            for yt, yp in zip(y_true, y_prob, strict=True)
            if (yp >= lo if index == 0 else yp > lo) and yp <= hi
        ]
        if not chosen:
            continue
        mean_p = sum(p for _, p in chosen) / len(chosen)
        mean_y = sum(y for y, _ in chosen) / len(chosen)
        gap = abs(mean_p - mean_y)
        max_abs = max(max_abs, gap)
        ece += gap * (len(chosen) / total)
        bins.append(
            {
                "bin": index,
                "lower": lo,
                "upper": hi,
                "count": len(chosen),
                "mean_predicted": round(mean_p, 6),
                "mean_actual": round(mean_y, 6),
                "abs_gap": round(gap, 6),
            }
        )
    return {"bins": bins, "ece": round(ece, 6), "max_abs_gap": round(max_abs, 6)}


def action_breakdown(
    rows: list[dict[str, Any]], y_prob: list[float]
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[tuple[int, float]]] = {}
    for row, prob in zip(rows, y_prob, strict=True):
        action = str(row["action"])
        grouped.setdefault(action, []).append((int(row["recovered"]), prob))
    report: dict[str, dict[str, float]] = {}
    for action, pairs in sorted(grouped.items()):
        actual = sum(y for y, _ in pairs) / len(pairs)
        predicted = sum(p for _, p in pairs) / len(pairs)
        report[action] = {
            "n": float(len(pairs)),
            "mean_predicted_probability": round(predicted, 6),
            "actual_recovery_rate": round(actual, 6),
            "gap": round(predicted - actual, 6),
        }
    return report
