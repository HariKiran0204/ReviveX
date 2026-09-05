from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.repositories import ModelPredictionRepository


def prediction_fingerprint(
    *,
    merchant_id: str,
    recovery_case_id: str,
    action: str,
    model_version: str,
    feature_version: str,
) -> str:
    payload = f"{merchant_id}|{recovery_case_id}|{action}|{model_version}|{feature_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def persist_prediction(
    session: Session,
    *,
    merchant_id: UUID,
    recovery_case_id: UUID,
    action: str,
    probability: float,
    model_version: str,
    feature_version: str,
    source: str,
    diagnostics: dict[str, Any] | None,
) -> str:
    if probability < 0.0 or probability > 1.0:
        raise ValueError("probability must be in [0, 1]")
    fingerprint = prediction_fingerprint(
        merchant_id=str(merchant_id),
        recovery_case_id=str(recovery_case_id),
        action=action,
        model_version=model_version,
        feature_version=feature_version,
    )
    ModelPredictionRepository(session).upsert(
        merchant_id=merchant_id,
        recovery_case_id=recovery_case_id,
        action=action,
        probability=Decimal(str(round(probability, 6))),
        model_version=model_version,
        feature_version=feature_version,
        fingerprint=fingerprint,
        source=source,
        diagnostics=diagnostics,
    )
    return fingerprint
