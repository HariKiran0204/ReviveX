from __future__ import annotations

from typing import Any

from recoverai_eval.constants import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from recoverai_eval.features.engineering import derive_features


def rows_to_xy(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    features: list[dict[str, Any]] = []
    labels: list[int] = []
    for row in rows:
        action = str(row["action"])
        features.append(derive_features(row, action))
        labels.append(int(row["recovered"]))
    return features, labels


def feature_frame(rows: list[dict[str, Any]]) -> Any:
    import pandas as pd

    frame = pd.DataFrame(rows)
    columns = list(NUMERIC_FEATURES) + list(CATEGORICAL_FEATURES)
    return frame.reindex(columns=columns)
