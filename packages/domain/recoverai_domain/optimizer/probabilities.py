from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.repositories import ModelPredictionRepository
from recoverai_domain.errors import OptimizerError
from recoverai_domain.optimizer.config import OptimizerSettings
from recoverai_domain.optimizer.erv import probability_to_decimal
from recoverai_domain.optimizer.types import ProbabilityQuote
from recoverai_eval.constants import FEATURE_VERSION
from recoverai_eval.errors import InferenceError
from recoverai_eval.inference.api import RecoveryProbability, predict_recovery_probability
from recoverai_eval.inference.fallback import FALLBACK_VERSION
from recoverai_eval.inference.persist import persist_prediction
from recoverai_eval.schema import CaseContext

Predictor = Callable[[CaseContext | dict[str, Any], str], RecoveryProbability]


def map_prediction_source(raw: str) -> str:
    if raw in {"ml", "MODEL"}:
        return "MODEL"
    if raw in {"MODEL_FALLBACK", FALLBACK_VERSION}:
        return "MODEL_FALLBACK"
    if raw == "OVERRIDE":
        return "OVERRIDE"
    return raw


def default_predictor(
    case_context: CaseContext | dict[str, Any], action: str
) -> RecoveryProbability:
    return predict_recovery_probability(case_context, action, allow_fallback=True)


def resolve_probability(
    *,
    action: str,
    ml_context: CaseContext | dict[str, Any] | None,
    overrides: Mapping[str, Decimal | float] | None,
    settings: OptimizerSettings,
    now: datetime,
    session: Session | None = None,
    merchant_id: UUID | None = None,
    recovery_case_id: UUID | None = None,
    predictor: Predictor | None = None,
) -> ProbabilityQuote | None:
    if overrides is not None and action in overrides:
        probability = probability_to_decimal(overrides[action])
        return ProbabilityQuote(
            probability=probability,
            model_version="override",
            feature_version=FEATURE_VERSION,
            source="OVERRIDE",
            predicted_at=now,
            stale=False,
            refreshed=False,
        )
    if overrides is not None:
        return None

    cached = _load_cached(
        session=session,
        recovery_case_id=recovery_case_id,
        action=action,
        now=now,
        ttl=timedelta(minutes=settings.prediction_ttl_minutes),
    )
    if cached is not None and not cached.stale:
        return cached

    quote = _predict(
        ml_context=ml_context,
        action=action,
        now=now,
        predictor=predictor or default_predictor,
        refreshed=cached is not None and cached.stale,
    )
    if session is not None and merchant_id is not None and recovery_case_id is not None:
        persist_source = "ml" if quote.source == "MODEL" else quote.source
        persist_prediction(
            session,
            merchant_id=merchant_id,
            recovery_case_id=recovery_case_id,
            action=action,
            probability=float(quote.probability),
            model_version=quote.model_version,
            feature_version=quote.feature_version,
            source=persist_source,
            diagnostics={"optimizer_version": settings.optimizer_version},
        )
    return quote


def _load_cached(
    *,
    session: Session | None,
    recovery_case_id: UUID | None,
    action: str,
    now: datetime,
    ttl: timedelta,
) -> ProbabilityQuote | None:
    if session is None or recovery_case_id is None:
        return None
    row = ModelPredictionRepository(session).get_latest_for_action(
        recovery_case_id=recovery_case_id, action=action
    )
    if row is None:
        return None
    predicted_at = row.updated_at or row.created_at
    if predicted_at.tzinfo is None:
        predicted_at = predicted_at.replace(tzinfo=UTC)
    stale = (now - predicted_at) > ttl
    return ProbabilityQuote(
        probability=probability_to_decimal(row.probability),
        model_version=row.model_version,
        feature_version=row.feature_version,
        source=map_prediction_source(row.source),
        predicted_at=predicted_at,
        stale=stale,
        refreshed=False,
    )


def _predict(
    *,
    ml_context: CaseContext | dict[str, Any] | None,
    action: str,
    now: datetime,
    predictor: Predictor,
    refreshed: bool,
) -> ProbabilityQuote:
    if ml_context is None:
        raise OptimizerError(
            "MISSING_CASE_CONTEXT",
            "A case context is required to score recovery probability",
        )
    try:
        scored = predictor(ml_context, action)
    except InferenceError as exc:
        raise OptimizerError(exc.code, exc.message) from exc
    probability = probability_to_decimal(scored.probability)
    source = map_prediction_source(scored.source)
    if source not in {"MODEL", "MODEL_FALLBACK", "OVERRIDE"}:
        source = "MODEL" if scored.source == "ml" else str(scored.source)
    return ProbabilityQuote(
        probability=probability,
        model_version=scored.model_version,
        feature_version=scored.feature_version,
        source=source,
        predicted_at=now,
        stale=False,
        refreshed=refreshed,
    )
