from decimal import Decimal

from recoverai_db.enums import PaymentStatus
from recoverai_providers.models import CreatePaymentRequest, CustomerHistory, FailureReason
from recoverai_providers.simulator.events import build_provider_event, deterministic_event_id
from recoverai_providers.simulator.interventions import (
    InterventionContext,
    intervention_recovery_probability,
)
from recoverai_providers.simulator.outcomes import capture_probability, roll_attempt_outcome
from recoverai_providers.simulator.provider import LocalSimulationProvider


def test_simulator_seed_is_reproducible() -> None:
    first = LocalSimulationProvider(seed=42)
    second = LocalSimulationProvider(seed=42)
    request = CreatePaymentRequest(
        merchant_reference="merchant-a",
        amount=Decimal("499.00"),
        failure_reason=FailureReason.TEMPORARY_BANK_ERROR,
        attempt_number=1,
        customer_history=CustomerHistory(prior_failures=2),
    )
    a = first.create_payment(request)
    b = second.create_payment(request)
    assert a.provider_payment_id == b.provider_payment_id
    assert a.status == b.status
    assert a.failure_reason == b.failure_reason
    assert a.provider_order_id == b.provider_order_id


def test_simulator_does_not_always_succeed() -> None:
    provider = LocalSimulationProvider(seed=7)
    failures = 0
    captures = 0
    for _ in range(20):
        snapshot = provider.create_payment(
            CreatePaymentRequest(
                merchant_reference="merchant-a",
                amount=Decimal("100.00"),
                failure_reason=FailureReason.INSUFFICIENT_FUNDS,
                attempt_number=1,
            )
        )
        if snapshot.status == PaymentStatus.FAILED:
            failures += 1
        if snapshot.status == PaymentStatus.CAPTURED:
            captures += 1
    assert failures >= 1
    assert captures + failures == 20


def test_customer_cancelled_never_captures() -> None:
    rng_provider = LocalSimulationProvider(seed=1)
    for _ in range(10):
        snapshot = rng_provider.create_payment(
            CreatePaymentRequest(
                merchant_reference="merchant-a",
                amount=Decimal("50.00"),
                failure_reason=FailureReason.CUSTOMER_CANCELLED,
            )
        )
        assert snapshot.status == PaymentStatus.CANCELLED


def test_intended_status_is_honored() -> None:
    provider = LocalSimulationProvider(seed=99)
    snapshot = provider.create_payment(
        CreatePaymentRequest(
            merchant_reference="merchant-a",
            amount=Decimal("10.00"),
            intended_status=PaymentStatus.FAILED,
            failure_reason=FailureReason.TEMPORARY_BANK_ERROR,
        )
    )
    assert snapshot.status == PaymentStatus.FAILED
    assert snapshot.failure_reason == FailureReason.TEMPORARY_BANK_ERROR


def test_deterministic_event_ids() -> None:
    assert deterministic_event_id(42, "pay_1", "payment.failed", 1) == deterministic_event_id(
        42, "pay_1", "payment.failed", 1
    )
    assert deterministic_event_id(42, "pay_1", "payment.failed", 1) != deterministic_event_id(
        43, "pay_1", "payment.failed", 1
    )


def test_build_provider_event_uses_simulator_provider() -> None:
    provider = LocalSimulationProvider(seed=42)
    snapshot = provider.create_payment(
        CreatePaymentRequest(
            merchant_reference="ref",
            amount=Decimal("1.00"),
            intended_status=PaymentStatus.FAILED,
            failure_reason=FailureReason.DECLINED,
        )
    )
    event = build_provider_event(snapshot, seed=42)
    assert event.provider == "SIMULATOR"
    assert event.event_type == "payment.failed"
    assert event.provider_resource_id != snapshot.merchant_reference
    event_again = build_provider_event(snapshot, seed=42)
    assert event.event_id == event_again.event_id


def test_intervention_probability_is_action_conditioned() -> None:
    ctx = InterventionContext(
        failure_reason=FailureReason.EXPIRED_CARD,
        attempt_number=1,
        history=CustomerHistory(),
        historical_success_rate=0.5,
        historical_recovery_rate=0.2,
        communication_count=1,
        previous_discount_usage=0.1,
        cart_age_hours=None,
        customer_lifetime_value=Decimal("1000.00"),
        amount=Decimal("400.00"),
        hour_of_day=12,
        case_type="FAILED_PAYMENT",
    )
    retry = intervention_recovery_probability(ctx, "RETRY_NOW")
    link = intervention_recovery_probability(ctx, "SEND_PAYMENT_LINK")
    assert link > retry
    bank = InterventionContext(
        failure_reason=FailureReason.TEMPORARY_BANK_ERROR,
        attempt_number=1,
        history=CustomerHistory(),
        historical_success_rate=0.7,
        historical_recovery_rate=0.3,
        communication_count=0,
        previous_discount_usage=0.0,
        cart_age_hours=None,
        customer_lifetime_value=Decimal("1000.00"),
        amount=Decimal("400.00"),
        hour_of_day=12,
        case_type="FAILED_PAYMENT",
    )
    assert intervention_recovery_probability(bank, "RETRY_NOW") > retry


def test_capture_probability_rises_with_retryable_attempts() -> None:
    history = CustomerHistory()
    first = capture_probability(FailureReason.TEMPORARY_BANK_ERROR, 1, history)
    later = capture_probability(FailureReason.TEMPORARY_BANK_ERROR, 4, history)
    assert later > first


def test_roll_attempt_outcome_intended_captured() -> None:
    import random

    status, reason = roll_attempt_outcome(
        random.Random(1),
        failure_reason=FailureReason.DECLINED,
        attempt_number=1,
        history=CustomerHistory(),
        intended_status=PaymentStatus.CAPTURED,
    )
    assert status == PaymentStatus.CAPTURED
    assert reason is None


def test_simulated_payment_link_is_not_razorpay() -> None:
    from recoverai_providers.models import CreatePaymentLinkRequest

    provider = LocalSimulationProvider(seed=42)
    link = provider.create_payment_link(
        CreatePaymentLinkRequest(
            merchant_reference="case-1",
            amount=Decimal("100.00"),
        )
    )
    assert link.provider == "SIMULATOR"
    assert link.simulated is True
    assert link.provider_payment_link_id.startswith("plink_sim_")
    assert link.url.startswith("sim://")
