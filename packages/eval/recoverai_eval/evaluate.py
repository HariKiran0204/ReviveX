from __future__ import annotations

import argparse
import json
from typing import Any

from recoverai_eval.data.generate import expand_with_labels, generate_cases
from recoverai_eval.data.split import split_by_customer
from recoverai_eval.evaluation.business_sense import directional_prediction_checks
from recoverai_eval.evaluation.metrics import (
    action_breakdown,
    calibration_curve_points,
    classification_metrics,
)
from recoverai_eval.features.dataset import feature_frame, rows_to_xy
from recoverai_eval.inference.api import predict_recovery_probability
from recoverai_eval.models.versioning import load_bundle
from recoverai_eval.schema import CaseContext


def evaluate(
    *, model_version: str | None = None, seed: int | None = None, n_cases: int | None = None
) -> dict[str, Any]:
    pipeline, metadata = load_bundle(model_version)
    used_seed = int(seed if seed is not None else metadata["seed"])
    used_n = int(n_cases if n_cases is not None else metadata["n_cases"])
    cases = generate_cases(seed=used_seed, n_cases=used_n)
    labeled = expand_with_labels(cases, seed=used_seed)
    splits = split_by_customer(labeled, seed=used_seed)
    held_out = splits["test"]
    x_rows, y_true = rows_to_xy(held_out)
    # Labels are used only for metrics. The model sees feature frame columns only.
    frame = feature_frame(x_rows)
    assert "recovered" not in frame.columns
    y_prob = [float(row[1]) for row in pipeline.predict_proba(frame)]
    metrics = classification_metrics(y_true, y_prob)
    calibration = calibration_curve_points(y_true, y_prob)
    # Spot-check public inference API on a few rows without passing labels.
    sample = held_out[0]
    context = CaseContext.model_validate(
        {key: sample[key] for key in CaseContext.model_fields if key in sample}
    )
    scored = predict_recovery_probability(
        context,
        str(sample["action"]),
        model_version=str(metadata.get("model_version")),
        allow_fallback=False,
    )
    return {
        "model_version": metadata.get("model_version"),
        "algorithm": metadata.get("algorithm"),
        "held_out": metrics,
        "calibration": calibration,
        "action_breakdown": action_breakdown(held_out, y_prob),
        "business_sense": directional_prediction_checks(held_out, y_prob),
        "inference_spot_check": {
            "probability": scored.probability,
            "model_version": scored.model_version,
        },
        "n_test_rows": len(held_out),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate a trained recovery-probability model")
    parser.add_argument("--model-version", type=str, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--n-cases", type=int, default=None)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            evaluate(model_version=args.model_version, seed=args.seed, n_cases=args.n_cases),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
