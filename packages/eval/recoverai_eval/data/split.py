from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from recoverai_eval.errors import ModelQualityError


def split_by_customer(
    rows: Sequence[dict[str, Any]],
    *,
    seed: int,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
) -> dict[str, list[dict[str, Any]]]:
    customers = sorted({str(row["customer_id"]) for row in rows})
    if len(customers) < 3:
        raise ModelQualityError(
            "INVALID_SPLIT", "Need at least 3 customers to split without leakage"
        )
    rng_customers = list(customers)
    # Deterministic shuffle independent of dict iteration order.
    import random

    random.Random(seed).shuffle(rng_customers)
    n_train = max(1, int(len(rng_customers) * train_ratio))
    n_val = max(1, int(len(rng_customers) * val_ratio))
    if n_train + n_val >= len(rng_customers):
        n_val = max(1, len(rng_customers) - n_train - 1)
    train_set = set(rng_customers[:n_train])
    val_set = set(rng_customers[n_train : n_train + n_val])
    test_set = set(rng_customers[n_train + n_val :])
    if not test_set:
        raise ModelQualityError("INVALID_SPLIT", "Held-out customer set is empty")
    overlap = (train_set & val_set) | (train_set & test_set) | (val_set & test_set)
    if overlap:
        raise ModelQualityError("INVALID_SPLIT", "Customer overlap across splits")

    buckets: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    for row in rows:
        customer = str(row["customer_id"])
        if customer in train_set:
            split = "train"
        elif customer in val_set:
            split = "validation"
        else:
            split = "test"
        copied = dict(row)
        copied["split"] = split
        buckets[split].append(copied)
    if not buckets["train"] or not buckets["validation"] or not buckets["test"]:
        raise ModelQualityError("INVALID_SPLIT", "A split received zero rows")
    return buckets


def split_ids(buckets: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {name: sorted({str(row["case_id"]) for row in rows}) for name, rows in buckets.items()}
