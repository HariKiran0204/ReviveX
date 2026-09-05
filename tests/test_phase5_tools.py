from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Thread
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_api.config import Settings
from recoverai_api.main import create_app
from recoverai_db.enums import (
    ApprovalStatus,
    PaymentStatus,
    RecoveryActionStatus,
    RecoveryActionType,
    RecoveryCaseStatus,
    RecoveryCaseType,
)
from recoverai_db.models import (
    Approval,
    Customer,
    Merchant,
    Notification,
    Payment,
    RecoveryAction,
    RecoveryCase,
)
from recoverai_db.session import SessionLocal
from recoverai_domain.errors import IdempotencyConflictError, ToolValidationError
from recoverai_domain.followups import apply_followups
from recoverai_domain.ingestion import ImmediateEventQueue
from recoverai_domain.processing import process_webhook_event
from recoverai_domain.processor import RecoveryCaseProcessor
from recoverai_domain.tools.approvals import ApprovalService
from recoverai_domain.tools.execution import ToolExecutionService
from recoverai_domain.verification import RecoveryVerificationService
from recoverai_providers.base import PaymentProvider
from recoverai_providers.errors import ProviderError
from recoverai_providers.models import (
    CreateOrderRequest,
    CreatePaymentLinkRequest,
    CreatePaymentRequest,
    OrderSnapshot,
    PaymentLinkSnapshot,
    PaymentSnapshot,
    RefundPaymentRequest,
)
from recoverai_providers.simulator.provider import LocalSimulationProvider


def _party(
    session: Session,
    suffix: str,
    amount: Decimal = Decimal("4000.00"),
    *,
    settings: dict | None = None,
    customer_meta: dict | None = None,
) -> tuple[Merchant, Customer, Payment, RecoveryCase]:
    merchant = Merchant(
        name=f"Tool Merchant {suffix}",
        slug=f"tool-{suffix}-{uuid4().hex[:8]}",
        settings=settings,
    )
    session.add(merchant)
    session.flush()
    customer = Customer(
        merchant_id=merchant.id,
        external_id=f"cust-{suffix}",
        email=f"{suffix}@example.test",
        full_name=suffix,
        lifetime_value=Decimal("0.00"),
        metadata_json=customer_meta,
    )
    session.add(customer)
    session.flush()
    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        provider="simulator",
        provider_payment_id=f"pay_orig_{suffix}_{uuid4().hex[:6]}",
        provider_order_id=f"order_{suffix}_{uuid4().hex[:6]}",
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
    RecoveryCaseProcessor(session).walk_to_policy_check(case)
    session.flush()
    return merchant, customer, payment, case


def _execute(
    session: Session,
    case: RecoveryCase,
    *,
    tool_name: str,
    idempotency_key: str,
    payload: dict | None = None,
    merchant_id=None,
    provider: PaymentProvider | None = None,
    approved: bool = False,
    approval_id=None,
    action_id=None,
):
    return ToolExecutionService(
        session, provider=provider or LocalSimulationProvider(seed=99)
    ).execute(
        case.id,
        tool_name=tool_name,
        payload=payload or {},
        idempotency_key=idempotency_key,
        merchant_id=merchant_id if merchant_id is not None else case.merchant_id,
        approved_execution=approved,
        approval_id=approval_id,
        existing_action_id=action_id,
    )


def test_invalid_tool_rejected(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "bad-tool")
    with pytest.raises(ToolValidationError) as exc:
        _execute(db_session, case, tool_name="invent_charge", idempotency_key="k1")
    assert exc.value.code == "UNKNOWN_TOOL"


def test_invalid_action_enum_rejected(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "bad-action")
    with pytest.raises(ToolValidationError) as exc:
        ToolExecutionService(db_session).execute(
            case.id,
            action="MAKE_ME_RICH",
            payload={},
            idempotency_key="k2",
            merchant_id=case.merchant_id,
        )
    assert exc.value.code == "UNKNOWN_ACTION"


def test_unsupported_fields_rejected(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "extra")
    with pytest.raises(ToolValidationError) as exc:
        _execute(
            db_session,
            case,
            tool_name="retry_payment",
            idempotency_key="k-extra",
            payload={"ignore_policy": True, "attempt_number": 1},
        )
    assert exc.value.code == "INVALID_TOOL_INPUT"


def test_missing_case_rejected(db_session: Session) -> None:
    with pytest.raises(Exception) as exc:
        ToolExecutionService(db_session).execute(
            uuid4(),
            tool_name="get_recovery_case",
            payload={},
            idempotency_key="k-missing",
        )
    assert getattr(exc.value, "code", "") == "RECOVERY_CASE_NOT_FOUND"


def test_wrong_merchant_rejected(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "wrong-m")
    with pytest.raises(ToolValidationError) as exc:
        _execute(
            db_session,
            case,
            tool_name="get_recovery_case",
            idempotency_key="k-merch",
            merchant_id=uuid4(),
        )
    assert exc.value.code == "MERCHANT_MISMATCH"


def test_retry_creates_new_attempt_and_keeps_original(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "retry")
    original_id = payment.provider_payment_id
    original_status = payment.status
    result = _execute(db_session, case, tool_name="retry_payment", idempotency_key="retry-1")
    assert result.status == "SUCCEEDED"
    db_session.refresh(payment)
    assert payment.provider_payment_id == original_id
    assert payment.status == original_status
    assert result.provider_reference != original_id
    assert result.output is not None
    assert result.output["original_provider_payment_id"] == original_id
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("0.00")


def test_duplicate_retry_does_not_execute_twice(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "retry-dup")
    first = _execute(db_session, case, tool_name="retry_payment", idempotency_key="retry-dup")
    second = _execute(db_session, case, tool_name="retry_payment", idempotency_key="retry-dup")
    assert first.status == "SUCCEEDED"
    assert second.replayed is True
    assert second.provider_reference == first.provider_reference
    actions = list(
        db_session.scalars(select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id))
    )
    succeeded = [item for item in actions if item.status == RecoveryActionStatus.SUCCEEDED]
    assert len(succeeded) == 1


def test_idempotency_conflict_different_payload(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "idemp-conflict")
    _execute(db_session, case, tool_name="retry_payment", idempotency_key="same-key")
    with pytest.raises(IdempotencyConflictError):
        _execute(
            db_session,
            case,
            tool_name="create_payment_link",
            idempotency_key="same-key",
            payload={},
        )


def test_payment_link_is_simulated(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "plink")
    result = _execute(db_session, case, tool_name="create_payment_link", idempotency_key="plink-1")
    assert result.status == "SUCCEEDED"
    assert result.provider == "SIMULATOR"
    assert result.simulated is True
    assert result.output is not None
    assert str(result.output["provider_payment_link_id"]).startswith("plink_sim_")
    assert str(result.output["url"]).startswith("sim://")


def test_valid_discount_executes_once(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "disc-ok")
    first = _execute(
        db_session,
        case,
        tool_name="offer_discount",
        idempotency_key="disc-1",
        payload={"discount_percent": "10"},
    )
    second = _execute(
        db_session,
        case,
        tool_name="offer_discount",
        idempotency_key="disc-1",
        payload={"discount_percent": "10"},
    )
    assert first.status == "SUCCEEDED"
    assert second.replayed is True
    assert first.output is not None
    assert first.output["discount_amount"] == "400.00"


def test_discount_over_percent_blocked(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "disc-block")
    result = _execute(
        db_session,
        case,
        tool_name="offer_discount",
        idempotency_key="disc-bad",
        payload={"discount_percent": "80"},
    )
    assert result.status == "BLOCKED"


def test_notification_opt_out_blocked(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(
        db_session, "notif-opt", customer_meta={"communication_opt_out": True}
    )
    result = _execute(
        db_session,
        case,
        tool_name="send_notification",
        idempotency_key="n1",
        payload={"channel": "EMAIL"},
    )
    assert result.status == "BLOCKED"


def test_valid_notification_executes(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "notif-ok")
    result = _execute(
        db_session,
        case,
        tool_name="send_notification",
        idempotency_key="n-ok",
        payload={"channel": "EMAIL", "subject": "Pay now"},
    )
    assert result.status == "SUCCEEDED"
    notes = list(
        db_session.scalars(select(Notification).where(Notification.recovery_case_id == case.id))
    )
    assert len(notes) == 1
    assert notes[0].provider == "SIMULATOR"


def test_notification_rate_limit_blocked(db_session: Session) -> None:
    merchant, customer, _payment, case = _party(db_session, "notif-rate")
    for _index in range(3):
        db_session.add(
            Notification(
                merchant_id=merchant.id,
                customer_id=customer.id,
                recovery_case_id=case.id,
                channel="EMAIL",
                status="SENT",
                provider="SIMULATOR",
            )
        )
    db_session.flush()
    result = _execute(
        db_session,
        case,
        tool_name="send_notification",
        idempotency_key="n-rate",
        payload={"channel": "EMAIL"},
    )
    assert result.status == "BLOCKED"


def test_schedule_retry_does_not_execute(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "sched")
    when = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    result = _execute(
        db_session,
        case,
        tool_name="schedule_retry",
        idempotency_key="sched-1",
        payload={"scheduled_for": when},
    )
    assert result.status == "SUCCEEDED"
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.RETRY_SCHEDULED
    action = db_session.scalars(
        select(RecoveryAction).where(RecoveryAction.idempotency_key == "sched-1")
    ).one()
    assert action.scheduled_for is not None
    assert action.metadata_json is not None
    assert action.metadata_json.get("executed") is False


def test_escalate_never_claims_recovery(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "esc")
    result = _execute(
        db_session,
        case,
        tool_name="escalate_to_human",
        idempotency_key="esc-1",
        payload={"reason": "Need a human"},
    )
    assert result.status == "SUCCEEDED"
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.ESCALATED
    assert case.amount_recovered == Decimal("0.00")


def test_approval_required_creates_approval(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "appr", Decimal("12000.00"))
    result = _execute(db_session, case, tool_name="retry_payment", idempotency_key="appr-1")
    assert result.status == "APPROVAL_REQUIRED"
    assert result.approval_id is not None
    approval = db_session.get(Approval, result.approval_id)
    assert approval is not None
    assert approval.status == ApprovalStatus.PENDING
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.AWAITING_APPROVAL


def test_unapproved_action_cannot_execute(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "unapp", Decimal("12000.00"))
    first = _execute(db_session, case, tool_name="retry_payment", idempotency_key="unapp-1")
    second = _execute(db_session, case, tool_name="retry_payment", idempotency_key="unapp-1")
    assert first.status == "APPROVAL_REQUIRED"
    assert second.status == "APPROVAL_REQUIRED"
    assert second.replayed is True
    action = db_session.get(RecoveryAction, first.action_id)
    assert action is not None
    assert action.status == RecoveryActionStatus.APPROVAL_REQUIRED


def test_approval_allows_action_after_revalidation(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "appr-ok", Decimal("12000.00"))
    pending = _execute(db_session, case, tool_name="retry_payment", idempotency_key="appr-ok")
    assert pending.action_id is not None
    result = ApprovalService(db_session, provider=LocalSimulationProvider(seed=3)).approve_action(
        case.id, pending.action_id, merchant_id=case.merchant_id
    )
    assert result.status == "SUCCEEDED"
    assert result.provider_reference is not None


def test_rejected_approval_cannot_execute(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "appr-rej", Decimal("12000.00"))
    pending = _execute(db_session, case, tool_name="retry_payment", idempotency_key="appr-rej")
    assert pending.action_id is not None
    ApprovalService(db_session).reject_action(
        case.id, pending.action_id, merchant_id=case.merchant_id
    )
    with pytest.raises(ToolValidationError) as exc:
        ApprovalService(db_session).approve_action(
            case.id, pending.action_id, merchant_id=case.merchant_id
        )
    assert exc.value.code in {"APPROVAL_NOT_PENDING", "ACTION_NOT_APPROVABLE"}


def test_expired_approval_cannot_execute(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "appr-exp", Decimal("12000.00"))
    pending = _execute(db_session, case, tool_name="retry_payment", idempotency_key="appr-exp")
    assert pending.approval_id is not None
    approval = db_session.get(Approval, pending.approval_id)
    assert approval is not None
    approval.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()
    assert pending.action_id is not None
    with pytest.raises(ToolValidationError) as exc:
        ApprovalService(db_session).approve_action(
            case.id, pending.action_id, merchant_id=case.merchant_id
        )
    assert exc.value.code == "APPROVAL_EXPIRED"


def test_policy_change_after_approval_is_reevaluated(db_session: Session) -> None:
    merchant, _customer, _payment, case = _party(db_session, "appr-pol", Decimal("12000.00"))
    pending = _execute(db_session, case, tool_name="retry_payment", idempotency_key="appr-pol")
    merchant.settings = {"policy": {"automatic_recovery_enabled": False}}
    db_session.flush()
    assert pending.action_id is not None
    result = ApprovalService(db_session, provider=LocalSimulationProvider(seed=4)).approve_action(
        case.id, pending.action_id, merchant_id=case.merchant_id
    )
    assert result.status == "BLOCKED"


def test_stale_approval_after_material_change(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "stale", Decimal("12000.00"))
    pending = _execute(db_session, case, tool_name="retry_payment", idempotency_key="stale")
    case.amount_at_risk = Decimal("15000.00")
    db_session.flush()
    assert pending.action_id is not None
    with pytest.raises(ToolValidationError) as exc:
        ApprovalService(db_session).approve_action(
            case.id, pending.action_id, merchant_id=case.merchant_id
        )
    assert exc.value.code == "STALE_APPROVAL"


class _FailingProvider(PaymentProvider):
    name = "SIMULATOR"

    def create_order(self, request: CreateOrderRequest) -> OrderSnapshot:
        raise ProviderError("PROVIDER_TIMEOUT", "simulator failed")

    def create_payment(self, request: CreatePaymentRequest) -> PaymentSnapshot:
        raise ProviderError("PROVIDER_TIMEOUT", "simulator failed")

    def fetch_payment(self, provider_payment_id: str) -> PaymentSnapshot:
        raise ProviderError("PROVIDER_TIMEOUT", "simulator failed")

    def fetch_order_payments(self, provider_order_id: str) -> list[PaymentSnapshot]:
        raise ProviderError("PROVIDER_TIMEOUT", "simulator failed")

    def refund_payment(self, request: RefundPaymentRequest) -> PaymentSnapshot:
        raise ProviderError("PROVIDER_TIMEOUT", "simulator failed")

    def create_payment_link(self, request: CreatePaymentLinkRequest) -> PaymentLinkSnapshot:
        raise ProviderError("PROVIDER_TIMEOUT", "simulator failed")


def test_provider_error_is_structured_failure(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "prov-fail")
    result = _execute(
        db_session,
        case,
        tool_name="retry_payment",
        idempotency_key="prov-fail",
        provider=_FailingProvider(),
    )
    assert result.status == "FAILED"
    assert "simulator failed" in result.reason
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.FAILED
    assert case.amount_recovered == Decimal("0.00")


def test_tool_cannot_credit_recovery(db_session: Session) -> None:
    _merchant, _customer, payment, case = _party(db_session, "no-credit")
    _execute(db_session, case, tool_name="retry_payment", idempotency_key="no-credit")
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("0.00")
    assert case.status != RecoveryCaseStatus.RECOVERED
    payment.status = PaymentStatus.CAPTURED
    payment.captured_at = datetime.now(UTC)
    verified = RecoveryVerificationService(db_session).verify_case(case.id, payment_id=payment.id)
    assert verified.matched is True
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.RECOVERED


def test_terminal_case_rejects_tools(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "term")
    case.status = RecoveryCaseStatus.STOPPED
    case.closed_at = datetime.now(UTC)
    db_session.flush()
    with pytest.raises(ToolValidationError) as exc:
        _execute(db_session, case, tool_name="retry_payment", idempotency_key="term")
    assert exc.value.code == "CASE_TERMINAL"


def test_read_only_tools(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "ro")
    history = _execute(db_session, case, tool_name="get_customer_history", idempotency_key="ro-1")
    details = _execute(db_session, case, tool_name="get_payment_details", idempotency_key="ro-2")
    prob = _execute(
        db_session, case, tool_name="calculate_recovery_probability", idempotency_key="ro-3"
    )
    assert history.status == "SUCCEEDED"
    assert details.status == "SUCCEEDED"
    assert prob.output is not None
    probability = prob.output["probability"]
    assert probability is not None
    assert 0.0 <= float(probability) <= 1.0
    assert prob.output["model_version"] is not None


def test_internal_evaluate_endpoint(db_session: Session) -> None:
    _merchant, _customer, _payment, case = _party(db_session, "api-eval")
    settings = Settings(app_env="development", database_url=None, redis_url=None)
    app = create_app(settings)
    app.state.event_queue = ImmediateEventQueue()
    app.state.db_session_factory = lambda: db_session
    with TestClient(app) as client:
        response = client.post(
            f"/v1/recovery-cases/{case.id}/actions/evaluate",
            json={"action": "RETRY_NOW", "merchant_id": str(case.merchant_id)},
        )
    assert response.status_code == 200
    body = response.json()["result"]
    assert body["allowed"] is True
    assert "policy_version" in body


def test_concurrent_identical_requests_one_side_effect(migrated_database: str) -> None:
    setup = SessionLocal(migrated_database)
    merchant, _customer, _payment, case = _party(setup, "conc")
    case_id = case.id
    merchant_id = merchant.id
    setup.commit()
    setup.close()

    results: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        session = SessionLocal(migrated_database)
        try:
            locked = session.get(RecoveryCase, case_id)
            assert locked is not None
            RecoveryCaseProcessor(session).walk_to_policy_check(locked)
            result = ToolExecutionService(
                session, provider=LocalSimulationProvider(seed=21)
            ).execute(
                case_id,
                tool_name="retry_payment",
                payload={},
                idempotency_key="conc-retry",
                merchant_id=merchant_id,
            )
            session.commit()
            results.append(result.status)
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
        actions = list(
            check.scalars(
                select(RecoveryAction).where(
                    RecoveryAction.recovery_case_id == case_id,
                    RecoveryAction.action_type == RecoveryActionType.RETRY_NOW,
                )
            )
        )
        succeeded = [item for item in actions if item.status == RecoveryActionStatus.SUCCEEDED]
        assert len(succeeded) == 1
        assert results.count("SUCCEEDED") >= 1
    finally:
        check.close()


def test_retry_payment_captured_reaches_recovered(
    db_session: Session,
) -> None:
    """End-to-end test: retry_payment with CAPTURED → event ingestion → verification → RECOVERED."""
    merchant, customer, original_payment, case = _party(db_session, "e2e-retry")
    original_payment_id = original_payment.id
    original_provider_id = original_payment.provider_payment_id

    # Execute retry with intended_status=CAPTURED
    queue = ImmediateEventQueue()
    result = ToolExecutionService(
        db_session, provider=LocalSimulationProvider(seed=42), queue=queue
    ).execute(
        case.id,
        tool_name="retry_payment",
        payload={"attempt_number": 1},
        idempotency_key="e2e-retry-captured",
        merchant_id=case.merchant_id,
    )
    assert result.status == "SUCCEEDED"
    assert result.output is not None
    new_payment_id_str = result.output.get("new_payment_id")
    assert new_payment_id_str is not None
    new_payment_id = UUID(new_payment_id_str)

    # Verify NEW payment was created with CAPTURED status
    new_payment = db_session.get(Payment, new_payment_id)
    assert new_payment is not None
    assert new_payment.status == PaymentStatus.CAPTURED
    assert new_payment.captured_at is not None
    assert new_payment.provider_payment_id != original_provider_id

    # Verify recovery_case.payment_id is still the ORIGINAL payment
    db_session.refresh(case)
    assert case.payment_id == original_payment_id
    assert case.payment_id != new_payment_id

    # Verify provider event was ingested and queued
    assert len(queue.enqueued) == 1
    webhook_event_id = queue.enqueued[0]
    queue.enqueued.clear()

    # Process the webhook event through normal worker path
    webhook_result = process_webhook_event(db_session, webhook_event_id)
    assert webhook_result["status"] == "processed"
    followups = webhook_result.get("followups")
    assert isinstance(followups, list)

    # Process verification followup
    verify_job = None
    for item in followups:
        if isinstance(item, dict) and item.get("name") == "verify_recovery_case":
            verify_job = item
            break
    assert verify_job is not None
    assert verify_job.get("payment_id") == str(new_payment_id)

    apply_followups(db_session, followups)

    # Verify case reached RECOVERED
    db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.RECOVERED
    assert case.amount_recovered == original_payment.amount
    assert case.verified_payment_id == new_payment_id
    assert case.verified_webhook_event_id == webhook_event_id

    # Verify idempotency: re-process same capture event
    webhook_result_2 = process_webhook_event(db_session, webhook_event_id)
    assert webhook_result_2["status"] == "already_processed"
    db_session.refresh(case)
    # No double counting
    assert case.amount_recovered == original_payment.amount
