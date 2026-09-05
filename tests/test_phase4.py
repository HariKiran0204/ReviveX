from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_api.config import Settings
from recoverai_api.main import create_app
from recoverai_db.enums import (
    PaymentStatus,
    RecoveryCaseStatus,
    RecoveryCaseType,
    WebhookEventStatus,
)
from recoverai_db.models import (
    AuditEvent,
    Customer,
    Merchant,
    Payment,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryDecision,
    WebhookEvent,
)
from recoverai_db.repositories import AuditEventRepository, RecoveryCaseRepository
from recoverai_db.session import SessionLocal
from recoverai_domain.audit import AuditEventType
from recoverai_domain.errors import InvalidTransitionError
from recoverai_domain.followups import apply_followups
from recoverai_domain.ingestion import ImmediateEventQueue
from recoverai_domain.money import as_money
from recoverai_domain.processing import process_webhook_event
from recoverai_domain.processor import process_recovery_case, verify_recovery_case
from recoverai_domain.recovery_config import RecoverySettings
from recoverai_domain.state_machine import can_transition
from recoverai_domain.transitions import lock_recovery_case, transition_case
from recoverai_domain.verification import RecoveryVerificationService
from recoverai_domain.verification_types import MismatchReason


def _party(
    session: Session, suffix: str, amount: Decimal = Decimal("4000.00")
) -> tuple[Merchant, Customer, Payment, RecoveryCase]:
    merchant = Merchant(name=f"Merchant {suffix}", slug=f"merchant-{suffix}-{uuid4().hex[:8]}")
    session.add(merchant)
    session.flush()
    customer = Customer(
        merchant_id=merchant.id,
        external_id=f"cust-{suffix}",
        email=f"{suffix}@example.test",
        full_name=suffix,
        lifetime_value=Decimal("0.00"),
    )
    session.add(customer)
    session.flush()
    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        provider="simulator",
        provider_payment_id=f"pay_{suffix}",
        provider_order_id=f"order_{suffix}",
        amount=amount,
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_code="TEMPORARY_BANK_ERROR",
        failed_at=datetime.now(UTC),
    )
    session.add(payment)
    session.flush()
    case = RecoveryCase(
        merchant_id=merchant.id,
        customer_id=customer.id,
        payment_id=payment.id,
        case_type=RecoveryCaseType.FAILED_PAYMENT,
        status=RecoveryCaseStatus.DETECTED,
        amount_at_risk=amount,
        amount_recovered=Decimal("0.00"),
        currency="INR",
        opened_at=datetime.now(UTC),
    )
    session.add(case)
    session.flush()
    return merchant, customer, payment, case


def test_legal_transitions_are_defined() -> None:
    assert can_transition(RecoveryCaseStatus.DETECTED, RecoveryCaseStatus.TRIAGED)
    assert can_transition(RecoveryCaseStatus.VERIFYING, RecoveryCaseStatus.RECOVERED)
    assert not can_transition(RecoveryCaseStatus.DETECTED, RecoveryCaseStatus.RECOVERED)


def test_valid_state_transition(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "valid-tx")
    transition_case(db_session, case, RecoveryCaseStatus.TRIAGED, correlation_id="c1")
    assert case.status == RecoveryCaseStatus.TRIAGED
    assert case.version == 2
    audits = AuditEventRepository(db_session).list_for_case(case.merchant_id, case.id)
    assert any(item.event_type == AuditEventType.CASE_TRIAGED for item in audits)


def test_invalid_state_transition_is_audited(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "invalid-tx")
    with pytest.raises(InvalidTransitionError) as exc:
        transition_case(db_session, case, RecoveryCaseStatus.RECOVERED)
    assert exc.value.code == "INVALID_STATE_TRANSITION"
    audits = AuditEventRepository(db_session).list_by_type(
        case.merchant_id, AuditEventType.STATE_TRANSITION_REJECTED
    )
    assert audits
    assert case.status == RecoveryCaseStatus.DETECTED
    assert case.amount_recovered == Decimal("0.00")


def test_detected_case_processing_is_deterministic(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "process")
    process_recovery_case(db_session, case.id)
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.ACTION_COMPLETED
    action = db_session.scalars(
        select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id)
    ).one()
    assert action.status == "PENDING"
    assert action.metadata_json is not None
    assert action.metadata_json.get("executed") is False
    assert action.action_type in {"RETRY_LATER", "SEND_PAYMENT_LINK"}
    types = {
        item.event_type
        for item in AuditEventRepository(db_session).list_for_case(case.merchant_id, case.id)
    }
    assert AuditEventType.CASE_TRIAGED in types
    assert AuditEventType.CASE_DIAGNOSED in types
    assert AuditEventType.RECOVERY_STRATEGY_SELECTED in types
    assert AuditEventType.RECOVERY_POLICY_CHECKED in types


def test_processor_is_idempotent(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "proc-idem")
    process_recovery_case(db_session, case.id)
    version = case.version
    process_recovery_case(db_session, case.id)
    assert case.status == RecoveryCaseStatus.ACTION_COMPLETED
    assert case.version == version
    actions = list(
        db_session.scalars(select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id))
    )
    assert len(actions) == 1


def _delete_case_tree(session: Session, case_id: object) -> None:
    case_row = session.get(RecoveryCase, case_id)
    if case_row is None:
        return
    payment_id = case_row.payment_id
    customer_id = case_row.customer_id
    merchant_id = case_row.merchant_id
    session.execute(
        sql_delete(RecoveryDecision).where(RecoveryDecision.recovery_case_id == case_id)
    )
    session.execute(sql_delete(RecoveryAction).where(RecoveryAction.recovery_case_id == case_id))
    session.execute(sql_delete(AuditEvent).where(AuditEvent.case_id == case_id))
    session.delete(case_row)
    session.flush()
    if payment_id is not None:
        session.execute(sql_delete(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id))
        payment = session.get(Payment, payment_id)
        if payment is not None:
            session.delete(payment)
            session.flush()
    customer = session.get(Customer, customer_id)
    merchant_row = session.get(Merchant, merchant_id)
    if customer is not None:
        session.delete(customer)
    if merchant_row is not None:
        session.delete(merchant_row)


def test_concurrent_transition_protection(migrated_database: str) -> None:
    setup = SessionLocal(migrated_database)
    leftovers = list(setup.scalars(select(Merchant).where(Merchant.slug.like("merchant-%"))).all())
    for merchant in leftovers:
        cases = list(
            setup.scalars(select(RecoveryCase).where(RecoveryCase.merchant_id == merchant.id)).all()
        )
        for leftover_case in cases:
            _delete_case_tree(setup, leftover_case.id)
    setup.commit()

    merchant, _customer, _payment, case = _party(setup, "concurrent")
    case_id = case.id
    setup.commit()
    setup.close()

    errors: list[BaseException] = []

    def worker() -> None:
        session = SessionLocal(migrated_database)
        try:
            locked = lock_recovery_case(session, case_id)
            transition_case(session, locked, RecoveryCaseStatus.TRIAGED)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            errors.append(exc)
        finally:
            session.close()

    first = Thread(target=worker)
    second = Thread(target=worker)
    first.start()
    second.start()
    first.join()
    second.join()

    check = SessionLocal(migrated_database)
    try:
        stored = check.get(RecoveryCase, case_id)
        assert stored is not None
        assert stored.status == RecoveryCaseStatus.TRIAGED
        assert stored.version == 2
        assert len(errors) == 1
        assert isinstance(errors[0], InvalidTransitionError)
    finally:
        _delete_case_tree(check, case_id)
        check.commit()
        check.close()


def _capture(payment: Payment, amount: Decimal | None = None) -> None:
    payment.status = PaymentStatus.CAPTURED
    payment.captured_at = datetime.now(UTC)
    if amount is not None:
        payment.amount = amount


def test_valid_capture_verifies_recovery(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "valid-cap")
    _capture(payment)
    result = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    assert result.matched is True
    assert result.amount_recovered == Decimal("4000.00")
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.RECOVERED
    assert case.amount_recovered == Decimal("4000.00")
    assert case.closed_at is not None
    assert isinstance(case.amount_recovered, Decimal)


def test_wrong_order_does_not_recover(db_session: Session) -> None:
    merchant, customer, payment, case = _party(db_session, "wrong-order")
    other = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        provider="simulator",
        provider_payment_id="pay_other_order",
        provider_order_id="order_other",
        amount=Decimal("4000.00"),
        currency="INR",
        status=PaymentStatus.CAPTURED,
        captured_at=datetime.now(UTC),
    )
    db_session.add(other)
    db_session.flush()
    result = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=other.id)
    assert result.matched is False
    assert result.mismatch_reason is MismatchReason.ORDER_MISMATCH
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.NOT_RECOVERED
    assert case.amount_recovered == Decimal("0.00")
    assert case.last_mismatch_reason == MismatchReason.ORDER_MISMATCH
    assert case.closed_at is None


def test_wrong_customer_does_not_recover(db_session: Session) -> None:
    merchant, _customer, _payment, case = _party(db_session, "wrong-cust")
    other_customer = Customer(
        merchant_id=merchant.id,
        external_id="other-cust",
        email="other@example.test",
        full_name="Other",
        lifetime_value=Decimal("0.00"),
    )
    db_session.add(other_customer)
    db_session.flush()
    other = Payment(
        merchant_id=merchant.id,
        customer_id=other_customer.id,
        provider="simulator",
        provider_payment_id="pay_other_cust",
        provider_order_id="order_wrong-cust",
        amount=Decimal("4000.00"),
        currency="INR",
        status=PaymentStatus.CAPTURED,
        captured_at=datetime.now(UTC),
    )
    db_session.add(other)
    db_session.flush()
    result = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=other.id)
    assert result.mismatch_reason is MismatchReason.CUSTOMER_MISMATCH
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("0.00")
    assert case.status != RecoveryCaseStatus.RECOVERED


def test_wrong_merchant_does_not_recover(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "wrong-merch-a")
    other_merchant, other_customer, other_payment, _other_case = _party(db_session, "wrong-merch-b")
    _capture(other_payment)
    result = RecoveryVerificationService(db_session).verify_case(
        case.id, payment_id=other_payment.id
    )
    assert result.mismatch_reason is MismatchReason.MERCHANT_MISMATCH
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("0.00")
    assert case.status != RecoveryCaseStatus.RECOVERED


def test_partial_capture_credits_only_valid_amount(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "partial")
    _capture(payment, Decimal("2000.00"))
    result = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    assert result.matched is False
    assert result.amount_recovered == Decimal("2000.00")
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("2000.00")
    assert case.amount_at_risk == Decimal("4000.00")
    assert case.status == RecoveryCaseStatus.NOT_RECOVERED
    remaining = as_money(case.amount_at_risk - case.amount_recovered)
    assert remaining == Decimal("2000.00")


def test_overpayment_is_capped(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "overpay")
    _capture(payment, Decimal("5000.00"))
    result = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    assert result.matched is True
    assert result.amount_recovered == Decimal("4000.00")
    assert result.capped_overpayment == Decimal("1000.00")
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("4000.00")
    assert case.amount_recovered <= case.amount_at_risk
    assert case.status == RecoveryCaseStatus.RECOVERED


def test_duplicate_capture_does_not_double_count(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "dup-cap")
    _capture(payment)
    event_id = uuid4()
    first = RecoveryVerificationService(db_session).verify_case(
        case.id, payment_id=payment.id, webhook_event_id=event_id
    )
    second = RecoveryVerificationService(db_session).verify_case(
        case.id, payment_id=payment.id, webhook_event_id=event_id
    )
    assert first.matched is True
    assert second.mismatch_reason is MismatchReason.DUPLICATE_EVENT
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("4000.00")


def test_already_counted_capture_ignored(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "counted")
    _capture(payment)
    RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    again = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    assert again.mismatch_reason is MismatchReason.ALREADY_COUNTED
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("4000.00")


def test_recovery_window_enforcement(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "window")
    case.opened_at = datetime.now(UTC) - timedelta(hours=100)
    _capture(payment)
    payment.captured_at = datetime.now(UTC)
    settings = RecoverySettings(recovery_window_hours=72, recovery_ordering_grace_minutes=60)
    result = RecoveryVerificationService(db_session, settings).verify_case(
        case.id, payment_id=payment.id
    )
    assert result.mismatch_reason is MismatchReason.OUTSIDE_RECOVERY_WINDOW
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("0.00")
    assert case.status != RecoveryCaseStatus.RECOVERED


def test_capture_before_case_within_grace(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "before")
    _capture(payment)
    payment.captured_at = case.opened_at - timedelta(minutes=10)
    settings = RecoverySettings(recovery_window_hours=72, recovery_ordering_grace_minutes=60)
    result = RecoveryVerificationService(db_session, settings).verify_case(
        case.id, payment_id=payment.id
    )
    assert result.matched is True
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.RECOVERED


def test_not_captured_is_rejected(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "not-cap")
    result = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    assert result.mismatch_reason is MismatchReason.NOT_CAPTURED
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("0.00")


def test_currency_mismatch(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "fx")
    _capture(payment)
    payment.currency = "USD"
    result = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    assert result.mismatch_reason is MismatchReason.CURRENCY_MISMATCH


def test_failed_verification_does_not_corrupt_amount(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "corrupt")
    payment.status = PaymentStatus.AUTHORIZED
    original_status = case.status
    RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("0.00")
    assert case.amount_at_risk == Decimal("4000.00")
    assert case.status != RecoveryCaseStatus.RECOVERED
    assert original_status == RecoveryCaseStatus.DETECTED


def test_verification_job_idempotency(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "job-idem")
    _capture(payment)
    first = verify_recovery_case(db_session, case.id, payment_id=payment.id)
    second = verify_recovery_case(db_session, case.id, payment_id=payment.id)
    assert first["matched"] is True
    assert second["matched"] is False
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("4000.00")


def test_capture_event_enqueues_verification_not_inline(db_session: Session) -> None:
    merchant, customer, payment, case = _party(db_session, "enqueue")

    webhook = WebhookEvent(
        merchant_id=merchant.id,
        provider="simulator",
        event_id=f"evt-{uuid4().hex[:8]}",
        event_type="payment.captured",
        status=WebhookEventStatus.RECEIVED,
        payload={
            "provider_payment_id": payment.provider_payment_id,
            "provider_order_id": payment.provider_order_id,
            "amount": "4000.00",
            "currency": "INR",
            "status": "CAPTURED",
            "customer_id": str(customer.id),
            "merchant_id": str(merchant.id),
        },
        received_at=datetime.now(UTC),
        signature_valid=True,
    )
    db_session.add(webhook)
    db_session.flush()
    result = process_webhook_event(db_session, webhook.id)
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.DETECTED
    assert case.amount_recovered == Decimal("0.00")
    followups = result["followups"]
    assert isinstance(followups, list)
    assert any(
        isinstance(item, dict) and item.get("name") == "verify_recovery_case" for item in followups
    )
    apply_followups(db_session, followups)
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.RECOVERED
    assert case.amount_recovered == Decimal("4000.00")


def test_capture_before_case_is_not_lost(db_session: Session) -> None:
    merchant, customer, payment, _case = _party(db_session, "lost")
    payment.status = PaymentStatus.CAPTURED
    payment.captured_at = datetime.now(UTC)
    db_session.flush()
    loaded = RecoveryCaseRepository(db_session).list_open_for_payment(merchant.id, payment.id)
    assert loaded
    result = RecoveryVerificationService(db_session).verify_case(
        loaded[0].id, payment_id=payment.id
    )
    assert result.matched is True


def test_demo_endpoints_use_backend_workflow(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "api")
    settings = Settings(app_env="development", database_url=None, redis_url=None)
    app = create_app(settings)
    app.state.event_queue = ImmediateEventQueue()
    app.state.db_session_factory = lambda: db_session
    with TestClient(app) as client:
        processed = client.post(f"/v1/recovery-cases/{case.id}/process")
        assert processed.status_code == 200
        db_session.refresh(case)
        assert case.status == RecoveryCaseStatus.ACTION_COMPLETED
        _capture(payment)
        verified = client.post(f"/v1/recovery-cases/{case.id}/verify")
        assert verified.status_code == 200
        body = verified.json()["result"]
        assert body["matched"] is True
        db_session.refresh(case)
        assert case.status == RecoveryCaseStatus.RECOVERED


def test_recovery_amount_never_exceeds_at_risk(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "cap-max", Decimal("10.00"))
    _capture(payment, Decimal("99.00"))
    RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    db_session.refresh(case)
    assert case.amount_recovered <= case.amount_at_risk
    assert case.amount_recovered == Decimal("10.00")
