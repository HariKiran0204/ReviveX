from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from recoverai_eval.constants import (
    DATASET_SCHEMA_VERSION,
    FEATURE_VERSION,
    MODEL_FEATURE_COLUMNS,
)
from recoverai_eval.data.generate import expand_with_labels, generate_cases
from recoverai_eval.data.split import split_by_customer, split_ids
from recoverai_eval.errors import ModelQualityError
from recoverai_eval.evaluation.business_sense import (
    assert_directional_labels,
    directional_prediction_checks,
)
from recoverai_eval.evaluation.metrics import (
    action_breakdown,
    calibration_curve_points,
    classification_metrics,
)
from recoverai_eval.evaluation.quality import run_quality_gates
from recoverai_eval.features.dataset import feature_frame, rows_to_xy
from recoverai_eval.features.engineering import assert_no_target_leakage
from recoverai_eval.models.pipelines import calibrate, forest_pipeline, logistic_pipeline
from recoverai_eval.models.versioning import (
    next_model_version,
    save_bundle,
    write_production_pointer,
)


def _predict_proba(model: Any, frame: Any) -> list[float]:
    raw = model.predict_proba(frame)
    return [float(row[1]) for row in raw]


def _fit_candidate(
    name: str,
    estimator: Any,
    x_train: Any,
    y_train: list[int],
    x_val: Any,
    y_val: list[int],
) -> dict[str, Any]:
    estimator.fit(x_train, y_train)
    calibrated = calibrate(estimator, x_val, y_val)
    val_prob = _predict_proba(calibrated, x_val)
    metrics = classification_metrics(y_val, val_prob)
    return {
        "name": name,
        "model": calibrated,
        "val_metrics": metrics,
        "val_brier": metrics["brier"],
        "val_roc_auc": metrics["roc_auc"],
    }


def train(
    *,
    seed: int = 42,
    n_cases: int = 10_000,
    model_version: str | None = None,
    overwrite: bool = False,
    forest_estimators: int = 80,
    persist_db: bool = False,
    publish: bool = True,
) -> dict[str, Any]:
    assert_no_target_leakage(list(MODEL_FEATURE_COLUMNS))
    cases = generate_cases(seed=seed, n_cases=n_cases)
    labeled = expand_with_labels(cases, seed=seed)
    assert_directional_labels(labeled)
    splits = split_by_customer(labeled, seed=seed)
    x_train_rows, y_train = rows_to_xy(splits["train"])
    x_val_rows, y_val = rows_to_xy(splits["validation"])
    x_test_rows, y_test = rows_to_xy(splits["test"])
    x_train = feature_frame(x_train_rows)
    x_val = feature_frame(x_val_rows)
    x_test = feature_frame(x_test_rows)

    logistic = _fit_candidate(
        "logistic_regression",
        logistic_pipeline(),
        x_train,
        y_train,
        x_val,
        y_val,
    )
    forest = _fit_candidate(
        "random_forest",
        forest_pipeline(seed=seed, n_estimators=forest_estimators, max_depth=12),
        x_train,
        y_train,
        x_val,
        y_val,
    )
    # Prefer logistic when Brier is effectively tied — simpler calibrated linear model.
    if forest["val_brier"] + 0.003 < logistic["val_brier"]:
        selected = forest
    else:
        selected = logistic

    test_prob = _predict_proba(selected["model"], x_test)
    test_metrics = classification_metrics(y_test, test_prob)
    calibration = calibration_curve_points(y_test, test_prob)
    ids = split_ids(splits)
    quality: dict[str, Any]
    quality_error: str | None = None
    try:
        quality = run_quality_gates(
            y_true=y_test,
            y_prob=test_prob,
            metrics=test_metrics,
            calibration=calibration,
            train_case_ids=set(ids["train"]),
            test_case_ids=set(ids["test"]),
            feature_names=list(MODEL_FEATURE_COLUMNS),
        )
    except ModelQualityError as exc:
        quality = {"passed": False, "failures": [exc.message]}
        quality_error = exc.message
        if publish:
            raise

    direction = directional_prediction_checks(splits["test"], test_prob)
    version = model_version or next_model_version()
    dataset_version = f"{DATASET_SCHEMA_VERSION}-seed{seed}-n{n_cases}"
    metadata = {
        "model_version": version,
        "dataset_version": dataset_version,
        "feature_version": FEATURE_VERSION,
        "seed": seed,
        "algorithm": selected["name"],
        "n_cases": n_cases,
        "n_rows": len(labeled),
        "n_features": len(MODEL_FEATURE_COLUMNS),
        "candidates": {
            logistic["name"]: {"val": logistic["val_metrics"]},
            forest["name"]: {"val": forest["val_metrics"]},
        },
        "selection_rule": "lowest validation Brier; logistic if within 0.003",
        "selected": selected["name"],
        "validation": selected["val_metrics"],
        "test": test_metrics,
        "calibration": calibration,
        "action_breakdown": action_breakdown(splits["test"], test_prob),
        "business_sense": direction,
        "quality": quality,
        "split": {name: len(rows) for name, rows in splits.items()},
        "trained_at": datetime.now(UTC).isoformat(),
        "configuration": {
            "forest_estimators": forest_estimators,
            "calibration": "isotonic_prefit_on_validation",
            "class_weight": "balanced",
        },
    }
    bundle_dir = save_bundle(
        version=version,
        pipeline=selected["model"],
        metadata=metadata,
        overwrite=overwrite,
    )
    (bundle_dir / "split_ids.json").write_text(json.dumps(ids, indent=2), encoding="utf-8")
    published = bool(quality.get("passed")) and publish
    if published:
        write_production_pointer(version)
    if persist_db:
        _persist_db_version(
            version=version,
            dataset_version=dataset_version,
            seed=seed,
            algorithm=str(selected["name"]),
            artifact_path=str(bundle_dir),
            quality_passed=bool(quality.get("passed")),
            is_production=published,
            metrics={
                "test": test_metrics,
                "validation": selected["val_metrics"],
                "quality": quality,
            },
            configuration=metadata["configuration"],
        )
    result = {
        "model_version": version,
        "selected": selected["name"],
        "test": test_metrics,
        "quality_passed": quality.get("passed"),
        "published": published,
        "artifact_path": str(bundle_dir),
        "quality_error": quality_error,
        "candidates": {
            "logistic_regression": logistic["val_metrics"],
            "random_forest": forest["val_metrics"],
        },
        "action_breakdown": metadata["action_breakdown"],
        "calibration": calibration,
        "n_cases": n_cases,
        "n_rows": len(labeled),
        "n_features": len(MODEL_FEATURE_COLUMNS),
    }
    return result


def _persist_db_version(**kwargs: Any) -> None:
    import os

    from recoverai_db.models import ModelVersion
    from recoverai_db.repositories import ModelVersionRepository
    from recoverai_db.session import get_session_factory

    url = os.environ.get("DATABASE_URL")
    if not url:
        return
    factory = get_session_factory(url)
    session = factory()
    try:
        repo = ModelVersionRepository(session)
        existing = repo.get_by_version(str(kwargs["version"]))
        if existing is not None:
            return
        if kwargs["is_production"]:
            repo.clear_production()
        repo.add(
            ModelVersion(
                id=uuid4(),
                version=kwargs["version"],
                algorithm=kwargs["algorithm"],
                dataset_version=kwargs["dataset_version"],
                feature_version=FEATURE_VERSION,
                seed=kwargs["seed"],
                trained_at=datetime.now(UTC),
                artifact_path=kwargs["artifact_path"],
                quality_passed=kwargs["quality_passed"],
                is_production=kwargs["is_production"],
                metrics=kwargs["metrics"],
                configuration=kwargs["configuration"],
            )
        )
        session.commit()
    finally:
        session.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Train RecoverAI recovery-probability models")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-cases", type=int, default=10_000)
    parser.add_argument("--model-version", type=str, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--forest-estimators", type=int, default=80)
    parser.add_argument("--persist-db", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    args = parser.parse_args(argv)
    result = train(
        seed=args.seed,
        n_cases=args.n_cases,
        model_version=args.model_version,
        overwrite=args.overwrite,
        forest_estimators=args.forest_estimators,
        persist_db=args.persist_db,
        publish=not args.no_publish,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
