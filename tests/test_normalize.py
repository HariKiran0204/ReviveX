from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from recoverai_api.events.service import webhook_to_provider_event
from recoverai_domain.errors import IngestionError
from recoverai_domain.events import DomainEventType, UnknownDomainEvent
from recoverai_domain.normalize import normalize_provider_event
from recoverai_providers.models import ProviderEvent, ProviderName


def test_normalize_failed_event() -> None:
    merchant_id = uuid4()
    webhook_id = uuid4()
    customer_id = uuid4()
    event = ProviderEvent(
        provider=ProviderName.SIMULATOR,
        event_id="evt_1",
        event_type="payment.failed",
        occurred_at=datetime.now(UTC),
        provider_resource_id="pay_sim_1",
        merchant_reference=str(merchant_id),
        payload={
            "amount": "10.00",
            "currency": "INR",
            "customer_id": str(customer_id),
            "failure_reason": "TEMPORARY_BANK_ERROR",
            "status": "FAILED",
        },
    )
    domain = normalize_provider_event(event, webhook_event_id=webhook_id, merchant_id=merchant_id)
    assert not isinstance(domain, UnknownDomainEvent)
    assert domain.event_type is DomainEventType.PAYMENT_FAILED
    assert domain.amount == Decimal("10.00")
    assert domain.provider_payment_id == "pay_sim_1"
    assert domain.customer_id == customer_id


def test_normalize_unknown_event() -> None:
    merchant_id = uuid4()
    event = ProviderEvent(
        provider=ProviderName.SIMULATOR,
        event_id="evt_x",
        event_type="payment.future_thing",
        occurred_at=datetime.now(UTC),
        provider_resource_id="pay_sim_x",
        merchant_reference="ref",
        payload={"amount": "1.00"},
    )
    domain = normalize_provider_event(event, webhook_event_id=uuid4(), merchant_id=merchant_id)
    assert isinstance(domain, UnknownDomainEvent)
    assert domain.raw_event_type == "payment.future_thing"


def test_webhook_rejects_missing_event_id() -> None:
    with pytest.raises(IngestionError) as exc:
        webhook_to_provider_event(
            event_id="  ",
            event_type="payment.failed",
            merchant_id=uuid4(),
            provider_resource_id="pay_1",
            amount=Decimal("1.00"),
        )
    assert exc.value.code == "INVALID_PROVIDER_EVENT"


def test_webhook_rejects_missing_amount_for_failure() -> None:
    with pytest.raises(IngestionError) as exc:
        webhook_to_provider_event(
            event_id="evt_1",
            event_type="payment.failed",
            merchant_id=uuid4(),
            provider_resource_id="pay_1",
        )
    assert exc.value.code == "INVALID_PROVIDER_EVENT"
