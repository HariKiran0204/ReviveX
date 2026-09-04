from __future__ import annotations

from datetime import UTC, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.enums import ActorType, PaymentStatus, RecoveryCaseStatus
from recoverai_db.models import Payment, RecoveryCase
from recoverai_db.repositories import PaymentRepository, RecoveryCaseRepository
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.errors import DomainError
from recoverai_domain.money import ZERO, as_money
from recoverai_domain.recovery_config import RecoverySettings, load_recovery_settings
from recoverai_domain.state_machine import coerce_status, is_terminal
from recoverai_domain.transitions import lock_recovery_case, transition_case
from recoverai_domain.verification_types import MismatchReason, RecoveryMatchResult


class RecoveryVerificationService:
    """Credits recovered revenue only when a captured payment matches the case."""

    def __init__(
        self,
        session: Session,
        settings: RecoverySettings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or load_recovery_settings()

    def verify_case(
        self,
        case_id: UUID,
        *,
        payment_id: UUID | None = None,
        webhook_event_id: UUID | None = None,
        correlation_id: str | None = None,
        actor_type: str = ActorType.WORKER,
    ) -> RecoveryMatchResult:
        case = lock_recovery_case(self._session, case_id)
        if is_terminal(case.status) and coerce_status(case.status) is RecoveryCaseStatus.STOPPED:
            return RecoveryMatchResult(
                matched=False,
                case_id=case.id,
                amount_recovered=as_money(case.amount_recovered),
                currency=case.currency,
                mismatch_reason=MismatchReason.UNKNOWN,
                remaining_exposure=as_money(case.amount_at_risk - case.amount_recovered),
                reasons=["case is STOPPED"],
            )

        payment = self._resolve_payment(case, payment_id)
        if payment is None:
            result = RecoveryMatchResult(
                matched=False,
                case_id=case.id,
                amount_recovered=ZERO,
                currency=case.currency,
                mismatch_reason=MismatchReason.PAYMENT_MISMATCH,
                remaining_exposure=as_money(case.amount_at_risk - case.amount_recovered),
            )
            self._persist_failure(case, result, webhook_event_id, correlation_id, actor_type)
            self._session.flush()
            return result

        duplicate = self._duplicate_or_already_counted(case, payment, webhook_event_id)
        if duplicate is not None:
            self._audit_no_credit(case, payment, duplicate, correlation_id, actor_type)
            self._session.flush()
            return duplicate

        match = self._evaluate(case, payment)
        match.payment_id = payment.id

        if coerce_status(case.status) is RecoveryCaseStatus.RECOVERED:
            return RecoveryMatchResult(
                matched=True,
                case_id=case.id,
                payment_id=payment.id,
                amount_recovered=as_money(case.amount_recovered),
                currency=case.currency,
                reasons=["already recovered; verification is idempotent"],
                remaining_exposure=ZERO,
            )

        self._ensure_verifying(case, correlation_id, actor_type)

        if match.matched:
            self._apply_success(case, payment, match, webhook_event_id, correlation_id, actor_type)
        else:
            self._persist_failure(case, match, webhook_event_id, correlation_id, actor_type)
        self._session.flush()
        return match

    def _resolve_payment(self, case: RecoveryCase, payment_id: UUID | None) -> Payment | None:
        target_id = payment_id or case.payment_id
        if target_id is None:
            return None
        return self._session.get(Payment, target_id)

    def _duplicate_or_already_counted(
        self,
        case: RecoveryCase,
        payment: Payment,
        webhook_event_id: UUID | None,
    ) -> RecoveryMatchResult | None:
        if (
            webhook_event_id is not None
            and case.verified_webhook_event_id is not None
            and case.verified_webhook_event_id == webhook_event_id
        ):
            return RecoveryMatchResult(
                matched=False,
                case_id=case.id,
                payment_id=payment.id,
                amount_recovered=as_money(case.amount_recovered),
                currency=case.currency,
                mismatch_reason=MismatchReason.DUPLICATE_EVENT,
                remaining_exposure=as_money(case.amount_at_risk - case.amount_recovered),
                reasons=["same capture event already verified"],
            )
        if case.verified_payment_id is not None and case.verified_payment_id == payment.id:
            return RecoveryMatchResult(
                matched=False,
                case_id=case.id,
                payment_id=payment.id,
                amount_recovered=as_money(case.amount_recovered),
                currency=case.currency,
                mismatch_reason=MismatchReason.ALREADY_COUNTED,
                remaining_exposure=as_money(case.amount_at_risk - case.amount_recovered),
                reasons=["this payment was already counted toward the case"],
            )
        counted = RecoveryCaseRepository(self._session).list_that_counted_payment(
            case.merchant_id, payment.id
        )
        other = [row for row in counted if row.id != case.id]
        if other:
            return RecoveryMatchResult(
                matched=False,
                case_id=case.id,
                payment_id=payment.id,
                amount_recovered=as_money(case.amount_recovered),
                currency=case.currency,
                mismatch_reason=MismatchReason.ALREADY_COUNTED,
                remaining_exposure=as_money(case.amount_at_risk - case.amount_recovered),
                reasons=["payment already counted on another recovery case"],
            )
        return None

    def _evaluate(self, case: RecoveryCase, payment: Payment) -> RecoveryMatchResult:
        remaining = as_money(case.amount_at_risk - case.amount_recovered)
        if payment.merchant_id != case.merchant_id:
            return self._mismatch(
                case,
                payment,
                MismatchReason.MERCHANT_MISMATCH,
                remaining,
                "merchant does not match",
            )
        if payment.customer_id != case.customer_id:
            return self._mismatch(
                case,
                payment,
                MismatchReason.CUSTOMER_MISMATCH,
                remaining,
                "customer does not match",
            )
        case_payment = None
        if case.payment_id is not None:
            case_payment = PaymentRepository(self._session).get_payment(
                case.merchant_id, case.payment_id
            )
            
        shared_order = False
        if (
            case_payment is not None
            and case_payment.provider_order_id
            and payment.provider_order_id
        ):
            if case_payment.provider_order_id != payment.provider_order_id:
                return self._mismatch(
                    case, payment, MismatchReason.ORDER_MISMATCH, remaining, "order does not match case"
                )
            shared_order = True

        if case.payment_id is not None and payment.id != case.payment_id:
            from sqlalchemy import select
            from recoverai_db.models import RecoveryAction
            
            linked_via_action = False
            actions = self._session.scalars(
                select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id)
            ).all()
            for action in actions:
                if action.provider_reference and action.provider_reference == payment.provider_payment_id:
                    linked_via_action = True
                    break
                if (action.metadata_json or {}).get("new_payment_id") == str(payment.id):
                    linked_via_action = True
                    break
                    
            if not (shared_order or linked_via_action):
                return self._mismatch(
                    case,
                    payment,
                    MismatchReason.PAYMENT_MISMATCH,
                    remaining,
                    "payment does not match case",
                )
        if payment.currency != case.currency:
            return self._mismatch(
                case,
                payment,
                MismatchReason.CURRENCY_MISMATCH,
                remaining,
                "currency does not match",
            )
        if payment.status != PaymentStatus.CAPTURED:
            return self._mismatch(
                case, payment, MismatchReason.NOT_CAPTURED, remaining, "payment is not CAPTURED"
            )
        if payment.captured_at is None:
            return self._mismatch(
                case, payment, MismatchReason.NOT_CAPTURED, remaining, "captured_at is missing"
            )
        if not self._inside_window(case, payment):
            return self._mismatch(
                case,
                payment,
                MismatchReason.OUTSIDE_RECOVERY_WINDOW,
                remaining,
                "capture is outside the recovery window",
            )

        captured = as_money(payment.amount)
        if captured <= ZERO:
            return self._mismatch(
                case,
                payment,
                MismatchReason.AMOUNT_MISMATCH,
                remaining,
                "captured amount is not positive",
            )

        at_risk = as_money(case.amount_at_risk)
        credited = min(captured, at_risk)
        overpayment = as_money(captured - credited) if captured > at_risk else ZERO
        reasons = [
            "merchant matches",
            "customer matches",
            "payment/order matches recovery context",
            "payment is CAPTURED",
            "capture is inside the recovery window",
            "payment was not previously counted",
        ]
        if captured < at_risk:
            reasons.append(
                "partial capture credited without treating full amount_at_risk as recovered"
            )
        if overpayment > ZERO:
            reasons.append("overpayment capped at amount_at_risk; excess is not recovery revenue")
        full = captured >= at_risk
        return RecoveryMatchResult(
            matched=full,
            case_id=case.id,
            payment_id=payment.id,
            amount_recovered=credited if full else captured,
            currency=case.currency,
            reasons=reasons,
            mismatch_reason=None if full else None,
            remaining_exposure=as_money(at_risk - (credited if full else captured)),
            capped_overpayment=overpayment,
        )

    def _mismatch(
        self,
        case: RecoveryCase,
        payment: Payment,
        reason: MismatchReason,
        remaining: Decimal,
        detail: str,
    ) -> RecoveryMatchResult:
        return RecoveryMatchResult(
            matched=False,
            case_id=case.id,
            payment_id=payment.id,
            amount_recovered=ZERO,
            currency=case.currency,
            mismatch_reason=reason,
            remaining_exposure=remaining,
            reasons=[detail],
        )

    def _inside_window(self, case: RecoveryCase, payment: Payment) -> bool:
        captured_at = payment.captured_at
        if captured_at is None:
            return False
        opened = case.opened_at
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=UTC)
        grace = timedelta(minutes=self._settings.recovery_ordering_grace_minutes)
        window = timedelta(hours=self._settings.recovery_window_hours)
        earliest = opened - grace
        latest = opened + window
        return earliest <= captured_at <= latest

    def _ensure_verifying(
        self,
        case: RecoveryCase,
        correlation_id: str | None,
        actor_type: str,
    ) -> None:
        status = coerce_status(case.status)
        if status is RecoveryCaseStatus.VERIFYING:
            return
        if status is RecoveryCaseStatus.RECOVERED:
            return
        if status is not RecoveryCaseStatus.ACTION_COMPLETED:
            from recoverai_domain.processor import RecoveryCaseProcessor

            RecoveryCaseProcessor(self._session, self._settings).process_locked_case(
                case, correlation_id=correlation_id, actor_type=actor_type
            )
        if coerce_status(case.status) is RecoveryCaseStatus.ACTION_COMPLETED:
            transition_case(
                self._session,
                case,
                RecoveryCaseStatus.VERIFYING,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary="Recovery verification started",
            )

    def _apply_success(
        self,
        case: RecoveryCase,
        payment: Payment,
        match: RecoveryMatchResult,
        webhook_event_id: UUID | None,
        correlation_id: str | None,
        actor_type: str,
    ) -> None:
        if coerce_status(case.status) is not RecoveryCaseStatus.VERIFYING:
            return
        previous_amount = as_money(case.amount_recovered)
        credited = as_money(match.amount_recovered)
        if credited > as_money(case.amount_at_risk):
            raise DomainError(
                "RECOVERY_AMOUNT_OVERFLOW",
                "amount_recovered would exceed amount_at_risk",
            )
        case.amount_recovered = credited
        case.verified_payment_id = payment.id
        case.verified_webhook_event_id = webhook_event_id
        case.last_mismatch_reason = None
        if previous_amount != credited:
            record_audit(
                self._session,
                merchant_id=case.merchant_id,
                case_id=case.id,
                event_type=AuditEventType.RECOVERY_AMOUNT_UPDATED,
                summary=(
                    f"Verified recovered amount updated from {previous_amount} to {credited} "
                    f"{case.currency}"
                ),
                actor_type=actor_type,
                action="update_amount_recovered",
                previous_state=str(previous_amount),
                new_state=str(credited),
                correlation_id=correlation_id,
                metadata={
                    "case_id": str(case.id),
                    "merchant_id": str(case.merchant_id),
                    "payment_id": str(payment.id),
                    "capped_overpayment": str(match.capped_overpayment),
                },
            )
        if coerce_status(case.status) is RecoveryCaseStatus.VERIFYING:
            transition_case(
                self._session,
                case,
                RecoveryCaseStatus.RECOVERED,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary="Capture matched the recovery case; recovered amount persisted",
                metadata={"payment_id": str(payment.id), "amount_recovered": str(credited)},
            )

    def _persist_failure(
        self,
        case: RecoveryCase,
        result: RecoveryMatchResult,
        webhook_event_id: UUID | None,
        correlation_id: str | None,
        actor_type: str,
    ) -> None:
        reason = result.mismatch_reason or MismatchReason.UNKNOWN
        case.last_mismatch_reason = str(reason)
        if (
            webhook_event_id is not None
            and result.mismatch_reason is MismatchReason.DUPLICATE_EVENT
        ):
            case.verified_webhook_event_id = webhook_event_id
        # Partial capture: credit without marking the full case recovered.
        if (
            result.mismatch_reason is None
            and result.amount_recovered > ZERO
            and result.remaining_exposure > ZERO
        ):
            previous_amount = as_money(case.amount_recovered)
            credited = as_money(min(result.amount_recovered, case.amount_at_risk))
            case.amount_recovered = credited
            if result.payment_id is not None:
                case.verified_payment_id = result.payment_id
            case.verified_webhook_event_id = webhook_event_id
            if previous_amount != credited:
                record_audit(
                    self._session,
                    merchant_id=case.merchant_id,
                    case_id=case.id,
                    event_type=AuditEventType.RECOVERY_AMOUNT_UPDATED,
                    summary=(
                        f"Partial capture credited {credited} {case.currency}; "
                        f"remaining exposure {result.remaining_exposure}"
                    ),
                    actor_type=actor_type,
                    action="update_amount_recovered",
                    previous_state=str(previous_amount),
                    new_state=str(credited),
                    correlation_id=correlation_id,
                    metadata={
                        "case_id": str(case.id),
                        "merchant_id": str(case.merchant_id),
                        "partial": True,
                    },
                )
        if coerce_status(case.status) is RecoveryCaseStatus.VERIFYING:
            transition_case(
                self._session,
                case,
                RecoveryCaseStatus.NOT_RECOVERED,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary=f"Recovery verification failed: {reason}",
                metadata={
                    "mismatch_reason": str(reason),
                    "payment_id": str(result.payment_id) if result.payment_id else None,
                },
            )
        elif result.mismatch_reason is not None:
            record_audit(
                self._session,
                merchant_id=case.merchant_id,
                case_id=case.id,
                event_type=AuditEventType.RECOVERY_VERIFICATION_FAILED,
                summary=f"Recovery verification failed: {reason}",
                actor_type=actor_type,
                action="verify_failed",
                previous_state=case.status,
                new_state=case.status,
                correlation_id=correlation_id,
                metadata={
                    "case_id": str(case.id),
                    "merchant_id": str(case.merchant_id),
                    "mismatch_reason": str(reason),
                },
            )

    def _audit_no_credit(
        self,
        case: RecoveryCase,
        payment: Payment,
        result: RecoveryMatchResult,
        correlation_id: str | None,
        actor_type: str,
    ) -> None:
        case.last_mismatch_reason = str(result.mismatch_reason) if result.mismatch_reason else None
        record_audit(
            self._session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.RECOVERY_VERIFICATION_FAILED,
            summary=(
                f"Verification ignored; no additional recovered revenue ({result.mismatch_reason})"
            ),
            actor_type=actor_type,
            action="verify_idempotent",
            previous_state=case.status,
            new_state=case.status,
            correlation_id=correlation_id,
            metadata={
                "case_id": str(case.id),
                "merchant_id": str(case.merchant_id),
                "payment_id": str(payment.id),
                "mismatch_reason": str(result.mismatch_reason),
                "amount_recovered": str(case.amount_recovered),
            },
        )
