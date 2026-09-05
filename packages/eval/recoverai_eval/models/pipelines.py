from __future__ import annotations

from typing import Any

from recoverai_eval.constants import CATEGORICAL_FEATURES, NUMERIC_FEATURES


def build_preprocessor() -> Any:
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    numeric = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="MISSING")),
            (
                "onehot",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
            ),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", numeric, list(NUMERIC_FEATURES)),
            ("cat", categorical, list(CATEGORICAL_FEATURES)),
        ]
    )


def logistic_pipeline(*, max_iter: int = 2000) -> Any:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    return Pipeline(
        steps=[
            ("pre", build_preprocessor()),
            (
                "clf",
                LogisticRegression(
                    max_iter=max_iter,
                    class_weight="balanced",
                    solver="lbfgs",
                ),
            ),
        ]
    )


def forest_pipeline(*, seed: int, n_estimators: int, max_depth: int) -> Any:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline

    return Pipeline(
        steps=[
            ("pre", build_preprocessor()),
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    min_samples_leaf=15,
                    class_weight="balanced",
                    random_state=seed,
                    n_jobs=1,
                ),
            ),
        ]
    )


def calibrate(estimator: Any, x_val: Any, y_val: list[int]) -> Any:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator

    calibrated = CalibratedClassifierCV(
        estimator=FrozenEstimator(estimator),
        method="isotonic",
    )
    calibrated.fit(x_val, y_val)
    return calibrated
