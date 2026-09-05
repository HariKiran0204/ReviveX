from __future__ import annotations

from recoverai_db.enums import TERMINAL_RECOVERY_STATUSES, RecoveryCaseStatus
from recoverai_domain.errors import InvalidTransitionError

LEGAL_TRANSITIONS: frozenset[tuple[RecoveryCaseStatus, RecoveryCaseStatus]] = frozenset(
    {
        (RecoveryCaseStatus.DETECTED, RecoveryCaseStatus.TRIAGED),
        (RecoveryCaseStatus.TRIAGED, RecoveryCaseStatus.INVESTIGATING),
        (RecoveryCaseStatus.TRIAGED, RecoveryCaseStatus.SCORING),
        (RecoveryCaseStatus.INVESTIGATING, RecoveryCaseStatus.DIAGNOSED),
        (RecoveryCaseStatus.DIAGNOSED, RecoveryCaseStatus.SCORING),
        (RecoveryCaseStatus.SCORING, RecoveryCaseStatus.STRATEGY_SELECTED),
        (RecoveryCaseStatus.STRATEGY_SELECTED, RecoveryCaseStatus.POLICY_CHECK),
        (RecoveryCaseStatus.POLICY_CHECK, RecoveryCaseStatus.EXECUTING),
        (RecoveryCaseStatus.POLICY_CHECK, RecoveryCaseStatus.STOPPED),
        (RecoveryCaseStatus.POLICY_CHECK, RecoveryCaseStatus.ESCALATED),
        (RecoveryCaseStatus.POLICY_CHECK, RecoveryCaseStatus.AWAITING_APPROVAL),
        (RecoveryCaseStatus.POLICY_CHECK, RecoveryCaseStatus.RETRY_SCHEDULED),
        (RecoveryCaseStatus.AWAITING_APPROVAL, RecoveryCaseStatus.EXECUTING),
        (RecoveryCaseStatus.AWAITING_APPROVAL, RecoveryCaseStatus.STOPPED),
        (RecoveryCaseStatus.AWAITING_APPROVAL, RecoveryCaseStatus.ESCALATED),
        (RecoveryCaseStatus.AWAITING_APPROVAL, RecoveryCaseStatus.POLICY_CHECK),
        (RecoveryCaseStatus.EXECUTING, RecoveryCaseStatus.ACTION_COMPLETED),
        (RecoveryCaseStatus.EXECUTING, RecoveryCaseStatus.FAILED),
        (RecoveryCaseStatus.ACTION_COMPLETED, RecoveryCaseStatus.VERIFYING),
        (RecoveryCaseStatus.VERIFYING, RecoveryCaseStatus.RECOVERED),
        (RecoveryCaseStatus.VERIFYING, RecoveryCaseStatus.NOT_RECOVERED),
        (RecoveryCaseStatus.VERIFYING, RecoveryCaseStatus.RETRY_SCHEDULED),
        (RecoveryCaseStatus.NOT_RECOVERED, RecoveryCaseStatus.RETRY_SCHEDULED),
        (RecoveryCaseStatus.NOT_RECOVERED, RecoveryCaseStatus.ESCALATED),
        (RecoveryCaseStatus.NOT_RECOVERED, RecoveryCaseStatus.STOPPED),
        (RecoveryCaseStatus.FAILED, RecoveryCaseStatus.RETRY_SCHEDULED),
        (RecoveryCaseStatus.FAILED, RecoveryCaseStatus.ESCALATED),
        (RecoveryCaseStatus.FAILED, RecoveryCaseStatus.STOPPED),
        (RecoveryCaseStatus.RETRY_SCHEDULED, RecoveryCaseStatus.SCORING),
        (RecoveryCaseStatus.ESCALATED, RecoveryCaseStatus.STOPPED),
    }
)

STARTING_STATUS = RecoveryCaseStatus.DETECTED

AUDIT_TYPE_FOR_TARGET: dict[RecoveryCaseStatus, str] = {
    RecoveryCaseStatus.TRIAGED: "CASE_TRIAGED",
    RecoveryCaseStatus.INVESTIGATING: "CASE_INVESTIGATING",
    RecoveryCaseStatus.DIAGNOSED: "CASE_DIAGNOSED",
    RecoveryCaseStatus.SCORING: "RECOVERY_SCORING_STARTED",
    RecoveryCaseStatus.STRATEGY_SELECTED: "RECOVERY_STRATEGY_SELECTED",
    RecoveryCaseStatus.POLICY_CHECK: "RECOVERY_POLICY_CHECKED",
    RecoveryCaseStatus.AWAITING_APPROVAL: "APPROVAL_REQUESTED",
    RecoveryCaseStatus.EXECUTING: "RECOVERY_EXECUTION_STARTED",
    RecoveryCaseStatus.ACTION_COMPLETED: "RECOVERY_ACTION_COMPLETED",
    RecoveryCaseStatus.VERIFYING: "RECOVERY_VERIFICATION_STARTED",
    RecoveryCaseStatus.RECOVERED: "RECOVERY_VERIFIED",
    RecoveryCaseStatus.NOT_RECOVERED: "RECOVERY_VERIFICATION_FAILED",
    RecoveryCaseStatus.STOPPED: "RECOVERY_CASE_STOPPED",
    RecoveryCaseStatus.ESCALATED: "RECOVERY_CASE_ESCALATED",
    RecoveryCaseStatus.FAILED: "RECOVERY_EXECUTION_STARTED",
    RecoveryCaseStatus.RETRY_SCHEDULED: "RECOVERY_VERIFICATION_FAILED",
}


def coerce_status(value: str | RecoveryCaseStatus) -> RecoveryCaseStatus:
    return value if isinstance(value, RecoveryCaseStatus) else RecoveryCaseStatus(value)


def is_terminal(status: str | RecoveryCaseStatus) -> bool:
    return coerce_status(status) in TERMINAL_RECOVERY_STATUSES


def can_transition(
    from_status: str | RecoveryCaseStatus, to_status: str | RecoveryCaseStatus
) -> bool:
    return (coerce_status(from_status), coerce_status(to_status)) in LEGAL_TRANSITIONS


def assert_legal_transition(
    from_status: str | RecoveryCaseStatus,
    to_status: str | RecoveryCaseStatus,
) -> None:
    source = coerce_status(from_status)
    target = coerce_status(to_status)
    if (source, target) not in LEGAL_TRANSITIONS:
        raise InvalidTransitionError(source, target)
