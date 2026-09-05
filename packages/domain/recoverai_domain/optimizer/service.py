from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.enums import RecoveryActionType, RiskLevel
from recoverai_db.models import RecoveryCase
from recoverai_db.repositories import CustomerRepository, PaymentRepository
from recoverai_domain.errors import OptimizerError
from recoverai_domain.money import ZERO, as_money
from recoverai_domain.optimizer.config import (
    LEGAL_ACTIONS,
    OptimizerSettings,
    load_optimizer_settings,
)
from recoverai_domain.optimizer.erv import (
    costs_for_action,
    expected_net_recovery,
    expected_recovered_revenue,
)
from recoverai_domain.optimizer.persist import persist_optimization_decision
from recoverai_domain.optimizer.probabilities import Predictor, resolve_probability
from recoverai_domain.optimizer.ranking import select_action
from recoverai_domain.optimizer.types import (
    CandidateAction,
    OptimizationResult,
    OptimizerCaseInput,
    ProbabilityQuote,
)
from recoverai_domain.policy_context import build_policy_context
from recoverai_domain.policy_engine import PolicyEngine
from recoverai_domain.policy_types import PolicyContext, PolicyEvaluationResult, ProposedAction
from recoverai_domain.recovery_config import RecoverySettings
from recoverai_eval.inference.domain import case_context_from_domain


class RecoveryOptimizer:
    """Deterministic ERV ranking. Does not execute tools, call providers, or credit recovery."""

    def __init__(
        self,
        settings: OptimizerSettings | None = None,
        *,
        policy_engine: PolicyEngine | None = None,
        recovery_settings: RecoverySettings | None = None,
        predictor: Predictor | None = None,
    ) -> None:
        self._settings = settings or load_optimizer_settings()
        self._policy_engine = policy_engine or PolicyEngine(recovery_settings)
        self._recovery_settings = recovery_settings
        self._predictor = predictor

    @property
    def settings(self) -> OptimizerSettings:
        return self._settings

    def optimize(
        self,
        case_context: OptimizerCaseInput,
        candidates: Sequence[str] | None = None,
        *,
        policy_context: PolicyContext | None = None,
        policy_results: Mapping[str, PolicyEvaluationResult] | None = None,
        probabilities: Mapping[str, Decimal | float] | None = None,
        now: datetime | None = None,
        session: Session | None = None,
        persist: bool = False,
        correlation_id: str | None = None,
    ) -> OptimizationResult:
        resolved_now = now or datetime.now(UTC)
        amount = as_money(case_context.amount_at_risk)
        actions = _normalize_candidates(candidates)
        discount_percent = (
            case_context.discount_percent
            if case_context.discount_percent is not None
            else self._settings.default_discount_percent
        )
        scored: list[CandidateAction] = []
        for action in actions:
            quote = resolve_probability(
                action=action,
                ml_context=case_context.ml_context,
                overrides=probabilities,
                settings=self._settings,
                now=resolved_now,
                session=session,
                merchant_id=case_context.merchant_id,
                recovery_case_id=case_context.case_id,
                predictor=self._predictor,
            )
            intervention, concession, communication, risk = costs_for_action(
                action,
                amount,
                self._settings,
                discount_percent=discount_percent
                if action == RecoveryActionType.OFFER_DISCOUNT.value
                else None,
            )
            policy = self._evaluate_policy(
                action,
                policy_context=policy_context,
                policy_results=policy_results,
                discount_percent=discount_percent,
                discount_amount=concession,
                session=session if persist else None,
                correlation_id=correlation_id,
            )
            scored.append(
                _candidate_from_quote(
                    action=action,
                    amount=amount,
                    quote=quote,
                    intervention_cost=intervention,
                    discount_cost=concession,
                    communication_cost=communication,
                    risk_penalty=risk,
                    policy=policy,
                    discount_percent=discount_percent
                    if action == RecoveryActionType.OFFER_DISCOUNT.value
                    else None,
                )
            )

        ordered = tuple(sorted(scored, key=lambda item: item.action))
        ranked_display = tuple(sorted(ordered, key=lambda item: item.action))
        ranked_display = tuple(
            sorted(ranked_display, key=lambda item: item.expected_value, reverse=True)
        )
        selected, reason = select_action(
            ordered,
            self._settings,
            suspicious=case_context.suspicious,
            source_mismatch=case_context.source_mismatch,
        )
        model_version, feature_version, prediction_source = _result_versions(ordered, selected)
        result = OptimizationResult(
            case_id=case_context.case_id,
            model_version=model_version,
            optimizer_version=self._settings.optimizer_version,
            feature_version=feature_version,
            candidate_actions=ranked_display,
            selected_action=selected.action if selected is not None else None,
            selected_expected_value=selected.expected_value if selected is not None else None,
            selection_reason=reason,
            prediction_source=prediction_source,
            requires_approval=selected.requires_approval if selected is not None else False,
        )
        if persist:
            if session is None:
                raise OptimizerError(
                    "MISSING_SESSION",
                    "Persisting an optimization decision requires a database session",
                )
            row = persist_optimization_decision(
                session,
                result,
                merchant_id=case_context.merchant_id,
                correlation_id=correlation_id,
            )
            result = OptimizationResult(
                case_id=result.case_id,
                model_version=result.model_version,
                optimizer_version=result.optimizer_version,
                feature_version=result.feature_version,
                candidate_actions=result.candidate_actions,
                selected_action=result.selected_action,
                selected_expected_value=result.selected_expected_value,
                selection_reason=result.selection_reason,
                prediction_source=result.prediction_source,
                requires_approval=result.requires_approval,
                decision_id=row.id,
            )
        return result

    def optimize_case(
        self,
        session: Session,
        case_id: UUID,
        *,
        persist: bool = True,
        probabilities: Mapping[str, Decimal | float] | None = None,
        now: datetime | None = None,
        correlation_id: str | None = None,
        candidates: Sequence[str] | None = None,
    ) -> OptimizationResult:
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise OptimizerError(
                "RECOVERY_CASE_NOT_FOUND",
                f"Recovery case {case_id} was not found",
            )
        recovered_before = case.amount_recovered
        policy_context = build_policy_context(
            session, case, settings=self._recovery_settings, now=now
        )
        payment = None
        if case.payment_id is not None:
            payment = PaymentRepository(session).get_payment(case.merchant_id, case.payment_id)
        customer = CustomerRepository(session).get_customer(case.merchant_id, case.customer_id)
        ml_context = case_context_from_domain(
            session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            amount=case.amount_at_risk,
            failure_reason=payment.failure_code if payment is not None else None,
            attempt_number=1,
            customer_id=case.customer_id,
            payment=payment,
            cart_id=case.cart_id,
            subscription_id=case.subscription_id,
            lifetime_value=customer.lifetime_value if customer is not None else None,
            opened_at=case.opened_at,
            case_type=case.case_type,
        )
        snapshot = OptimizerCaseInput(
            case_id=case.id,
            merchant_id=case.merchant_id,
            amount_at_risk=case.amount_at_risk,
            amount_recovered=case.amount_recovered,
            currency=case.currency,
            suspicious=policy_context.suspicious,
            source_mismatch=policy_context.source_mismatch,
            discount_percent=self._settings.default_discount_percent,
            ml_context=ml_context.model_dump(),
        )
        result = self.optimize(
            snapshot,
            candidates,
            policy_context=policy_context,
            probabilities=probabilities,
            now=now,
            session=session,
            persist=persist,
            correlation_id=correlation_id,
        )
        if case.amount_recovered != recovered_before:
            raise OptimizerError(
                "OPTIMIZER_MUTATED_RECOVERY",
                "RecoveryOptimizer must not change amount_recovered",
            )
        return result

    def _evaluate_policy(
        self,
        action: str,
        *,
        policy_context: PolicyContext | None,
        policy_results: Mapping[str, PolicyEvaluationResult] | None,
        discount_percent: Decimal,
        discount_amount: Decimal,
        session: Session | None,
        correlation_id: str | None,
    ) -> PolicyEvaluationResult:
        if policy_results is not None and action in policy_results:
            return policy_results[action]
        if policy_context is None:
            return PolicyEvaluationResult(
                allowed=True,
                requires_approval=False,
                risk_level=RiskLevel.GREEN,
                reason="No PolicyContext provided; caller injected an unconstrained ranking",
                policy_ids=["optimizer_unconstrained"],
            )
        proposed = ProposedAction(
            action_type=action,
            discount_percent=discount_percent
            if action == RecoveryActionType.OFFER_DISCOUNT.value
            else None,
            discount_amount=discount_amount
            if action == RecoveryActionType.OFFER_DISCOUNT.value
            else None,
        )
        if session is not None:
            return self._policy_engine.evaluate_and_persist(
                session,
                policy_context,
                proposed,
                correlation_id=correlation_id,
            )
        return self._policy_engine.evaluate_action(policy_context, proposed)


def _normalize_candidates(candidates: Sequence[str] | None) -> tuple[str, ...]:
    if candidates is None:
        return LEGAL_ACTIONS
    unique: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        action = str(raw)
        if action in seen:
            continue
        if action not in LEGAL_ACTIONS:
            raise OptimizerError("INVALID_ACTION", f"Unknown recovery action: {action}")
        seen.add(action)
        unique.append(action)
    return tuple(unique)


def _candidate_from_quote(
    *,
    action: str,
    amount: Decimal,
    quote: ProbabilityQuote | None,
    intervention_cost: Decimal,
    discount_cost: Decimal,
    communication_cost: Decimal,
    risk_penalty: Decimal,
    policy: PolicyEvaluationResult,
    discount_percent: Decimal | None,
) -> CandidateAction:
    if quote is None:
        return CandidateAction(
            action=action,
            probability=None,
            amount_at_risk=amount,
            expected_recovery=ZERO,
            intervention_cost=intervention_cost,
            discount_cost=discount_cost,
            communication_cost=communication_cost,
            risk_penalty=risk_penalty,
            expected_value=ZERO,
            allowed=False,
            requires_approval=False,
            policy_reason="Missing candidate probability; excluded from ranking",
            missing_probability=True,
            discount_percent=discount_percent,
            policy_ids=tuple(policy.policy_ids),
            risk_level=str(policy.risk_level),
        )
    expected_recovery = expected_recovered_revenue(quote.probability, amount)
    expected_value = expected_net_recovery(
        probability=quote.probability,
        amount_at_risk=amount,
        intervention_cost=intervention_cost,
        discount_cost_value=discount_cost,
        communication_cost=communication_cost,
        risk_penalty=risk_penalty,
    )
    return CandidateAction(
        action=action,
        probability=quote.probability,
        amount_at_risk=amount,
        expected_recovery=expected_recovery,
        intervention_cost=intervention_cost,
        discount_cost=discount_cost,
        communication_cost=communication_cost,
        risk_penalty=risk_penalty,
        expected_value=expected_value,
        allowed=policy.allowed,
        requires_approval=policy.requires_approval and policy.allowed,
        policy_reason=policy.reason,
        prediction_source=quote.source,
        model_version=quote.model_version,
        feature_version=quote.feature_version,
        prediction_timestamp=quote.predicted_at,
        stale_prediction=quote.stale,
        missing_probability=False,
        discount_percent=discount_percent,
        policy_ids=tuple(policy.policy_ids),
        risk_level=str(policy.risk_level),
    )


def _result_versions(
    candidates: tuple[CandidateAction, ...] | list[CandidateAction],
    selected: CandidateAction | None,
) -> tuple[str, str | None, str | None]:
    focus = selected
    if focus is None:
        with_model = [item for item in candidates if item.model_version]
        focus = with_model[0] if with_model else None
    if focus is None:
        return "unknown", None, None
    return (
        focus.model_version or "unknown",
        focus.feature_version,
        focus.prediction_source,
    )
