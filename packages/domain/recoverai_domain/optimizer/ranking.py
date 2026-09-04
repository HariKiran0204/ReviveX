from __future__ import annotations

from recoverai_db.enums import RecoveryActionType
from recoverai_domain.money import ZERO, signed_money
from recoverai_domain.optimizer.config import (
    CONTROL_STRATEGIES,
    FRICTION_RANK,
    RECOVERY_INTERVENTIONS,
    SIMPLICITY_RANK,
    OptimizerSettings,
)
from recoverai_domain.optimizer.types import CandidateAction

_RECOVERY = {item.value for item in RECOVERY_INTERVENTIONS}
_CONTROL = {item.value for item in CONTROL_STRATEGIES}


def _tie_key(candidate: CandidateAction) -> tuple[int, object, object, int, str]:
    total_direct_cost = (
        candidate.intervention_cost + candidate.communication_cost + candidate.discount_cost
    )
    return (
        FRICTION_RANK.get(candidate.action, 99),
        total_direct_cost,
        candidate.risk_penalty,
        SIMPLICITY_RANK.get(candidate.action, 99),
        candidate.action,
    )


def eligible_candidates(candidates: tuple[CandidateAction, ...]) -> tuple[CandidateAction, ...]:
    return tuple(
        item
        for item in candidates
        if item.allowed and not item.missing_probability and item.probability is not None
    )


def select_action(
    candidates: tuple[CandidateAction, ...],
    settings: OptimizerSettings,
    *,
    suspicious: bool,
    source_mismatch: bool,
) -> tuple[CandidateAction | None, str]:
    """
    Pick the highest-ERV permitted recovery intervention when any has ERV >= 0.

    If every permitted recovery intervention has negative ERV (or none are permitted),
    choose DO_NOTHING or ESCALATE from policy/risk — not the least-negative recovery action.

    Ties (ERV within tie_epsilon of the group max): lower friction, then lower direct cost,
    then lower risk_penalty, then simpler action, then action name.
    """
    eligible = eligible_candidates(candidates)
    if not eligible:
        return None, "No policy-permitted candidate with a valid probability remains"

    recovery = [item for item in eligible if item.action in _RECOVERY]
    non_negative_recovery = [item for item in recovery if item.expected_value >= ZERO]
    if non_negative_recovery:
        winner = _max_with_ties(tuple(non_negative_recovery), settings)
        reason = (
            f"Selected {winner.action} with maximum expected recovery value "
            f"{winner.expected_value} among policy-permitted recovery interventions"
        )
        if winner.requires_approval:
            reason += "; execution still requires human approval"
        return winner, reason

    return _select_control(
        eligible,
        suspicious=suspicious or source_mismatch,
    )


def _max_with_ties(
    pool: tuple[CandidateAction, ...], settings: OptimizerSettings
) -> CandidateAction:
    ranked = sorted(pool, key=lambda item: item.expected_value, reverse=True)
    best = ranked[0]
    epsilon = signed_money(settings.tie_epsilon)
    tied = tuple(item for item in ranked if (best.expected_value - item.expected_value) <= epsilon)
    return sorted(tied, key=_tie_key)[0]


def _select_control(
    eligible: tuple[CandidateAction, ...],
    *,
    suspicious: bool,
) -> tuple[CandidateAction | None, str]:
    by_action = {item.action: item for item in eligible}
    nothing = by_action.get(RecoveryActionType.DO_NOTHING.value)
    escalate = by_action.get(RecoveryActionType.ESCALATE.value)
    if suspicious and escalate is not None:
        return (
            escalate,
            "Recovery interventions are uneconomic or unavailable; "
            "ESCALATE selected because the case is high-risk",
        )
    if nothing is not None:
        return (
            nothing,
            "Every permitted recovery intervention has negative expected value; "
            "DO_NOTHING selected for economic discipline",
        )
    if escalate is not None:
        return (
            escalate,
            "Every permitted recovery intervention has negative expected value; "
            "ESCALATE selected because DO_NOTHING is not permitted",
        )
    control = [item for item in eligible if item.action in _CONTROL]
    if control:
        chosen = control[0]
        return chosen, f"Fell back to control strategy {chosen.action}"
    return None, "No permitted recovery or control strategy remains"
