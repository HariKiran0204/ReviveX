from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from recoverai_eval.constants import FEATURE_VERSION
from recoverai_eval.errors import InferenceError
from recoverai_eval.features.dataset import feature_frame
from recoverai_eval.features.engineering import features_from_context
from recoverai_eval.inference.fallback import FALLBACK_VERSION, fallback_probability
from recoverai_eval.models.versioning import load_bundle
from recoverai_eval.schema import CaseContext, parse_action

_pipeline_cache: dict[str, tuple[Any, dict[str, Any]]] = {}


@dataclass(frozen=True)
class RecoveryProbability:
    probability: float
    model_version: str
    feature_version: str
    source: Literal["ml", "MODEL_FALLBACK"]
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _validate_probability(value: float) -> float:
    if value < 0.0 or value > 1.0:
        raise InferenceError("INVALID_PROBABILITY", f"Probability {value} is outside [0, 1]")
    return float(value)


def _load(version: str | None) -> tuple[Any, dict[str, Any]]:
    key = version or "__production__"
    cached = _pipeline_cache.get(key)
    if cached is not None:
        return cached
    bundle = load_bundle(version)
    _pipeline_cache[key] = bundle
    return bundle


def clear_model_cache() -> None:
    _pipeline_cache.clear()


def _ml_predict(
    context: CaseContext, action: str, *, model_version: str | None
) -> RecoveryProbability:
    pipeline, metadata = _load(model_version)
    frame = feature_frame([features_from_context(context, action)])
    raw = pipeline.predict_proba(frame)
    probability = _validate_probability(float(raw[0][1]))
    version = str(metadata.get("model_version") or model_version or "unknown")
    feature_version = str(metadata.get("feature_version") or FEATURE_VERSION)
    return RecoveryProbability(
        probability=probability,
        model_version=version,
        feature_version=feature_version,
        source="ml",
        diagnostics={"algorithm": metadata.get("algorithm")},
    )


def predict_recovery_probability(
    case_context: CaseContext | dict[str, Any],
    action: str,
    *,
    model_version: str | None = None,
    allow_fallback: bool = True,
) -> RecoveryProbability:
    """P(recovery | case context, action). Does not choose or execute an action."""
    parsed_action = parse_action(action)
    try:
        context = (
            case_context
            if isinstance(case_context, CaseContext)
            else CaseContext.model_validate(case_context)
        )
    except ValidationError as exc:
        raise InferenceError("MALFORMED_FEATURES", str(exc)) from exc
    try:
        return _ml_predict(context, parsed_action, model_version=model_version)
    except InferenceError:
        if not allow_fallback:
            raise
        probability = _validate_probability(fallback_probability(context, parsed_action))
        return RecoveryProbability(
            probability=probability,
            model_version=FALLBACK_VERSION,
            feature_version=FEATURE_VERSION,
            source="MODEL_FALLBACK",
            diagnostics={"reason": "trained_model_unavailable_or_unloadable"},
        )
