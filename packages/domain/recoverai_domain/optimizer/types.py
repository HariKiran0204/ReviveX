from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

PredictionSource = Literal["MODEL", "MODEL_FALLBACK", "OVERRIDE"]


@dataclass(frozen=True)
class ProbabilityQuote:
    probability: Decimal
    model_version: str
    feature_version: str
    source: str
    predicted_at: datetime | None
    stale: bool = False
    refreshed: bool = False


@dataclass(frozen=True)
class CandidateAction:
    action: str
    probability: Decimal | None
    amount_at_risk: Decimal
    expected_recovery: Decimal
    intervention_cost: Decimal
    discount_cost: Decimal
    communication_cost: Decimal
    risk_penalty: Decimal
    expected_value: Decimal
    allowed: bool
    requires_approval: bool
    policy_reason: str
    prediction_source: str | None = None
    model_version: str | None = None
    feature_version: str | None = None
    prediction_timestamp: datetime | None = None
    stale_prediction: bool = False
    missing_probability: bool = False
    discount_percent: Decimal | None = None
    policy_ids: tuple[str, ...] = ()
    risk_level: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "probability": str(self.probability) if self.probability is not None else None,
            "amount_at_risk": str(self.amount_at_risk),
            "expected_recovery": str(self.expected_recovery),
            "intervention_cost": str(self.intervention_cost),
            "discount_cost": str(self.discount_cost),
            "communication_cost": str(self.communication_cost),
            "risk_penalty": str(self.risk_penalty),
            "expected_value": str(self.expected_value),
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "policy_reason": self.policy_reason,
            "prediction_source": self.prediction_source,
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "prediction_timestamp": (
                self.prediction_timestamp.isoformat() if self.prediction_timestamp else None
            ),
            "stale_prediction": self.stale_prediction,
            "missing_probability": self.missing_probability,
            "discount_percent": (
                str(self.discount_percent) if self.discount_percent is not None else None
            ),
            "policy_ids": list(self.policy_ids),
            "risk_level": self.risk_level,
        }


@dataclass(frozen=True)
class OptimizationResult:
    case_id: UUID
    model_version: str
    optimizer_version: str
    feature_version: str | None
    candidate_actions: tuple[CandidateAction, ...]
    selected_action: str | None
    selected_expected_value: Decimal | None
    selection_reason: str
    prediction_source: str | None = None
    requires_approval: bool = False
    decision_id: UUID | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "case_id": str(self.case_id),
            "model_version": self.model_version,
            "optimizer_version": self.optimizer_version,
            "feature_version": self.feature_version,
            "candidate_actions": [item.to_public_dict() for item in self.candidate_actions],
            "selected_action": self.selected_action,
            "selected_expected_value": (
                str(self.selected_expected_value)
                if self.selected_expected_value is not None
                else None
            ),
            "selection_reason": self.selection_reason,
            "prediction_source": self.prediction_source,
            "requires_approval": self.requires_approval,
            "decision_id": str(self.decision_id) if self.decision_id else None,
        }


@dataclass(frozen=True)
class OptimizerCaseInput:
    """Read-only case snapshot for ranking. Never includes write handles."""

    case_id: UUID
    merchant_id: UUID
    amount_at_risk: Decimal
    amount_recovered: Decimal
    currency: str = "INR"
    suspicious: bool = False
    source_mismatch: bool = False
    discount_percent: Decimal | None = None
    ml_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class BatchOptimizationResult:
    optimizer_version: str
    results: tuple[OptimizationResult, ...]
    case_count: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_count", len(self.results))
