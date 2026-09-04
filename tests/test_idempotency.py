from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from recoverai_db.enums import IdempotencyKeyStatus
from recoverai_db.models import IdempotencyKey, Merchant


def test_idempotency_key_unique_per_merchant(db_session) -> None:
    merchant = Merchant(name="Idempotency Merchant", slug="idempotency-merchant")
    db_session.add(merchant)
    db_session.flush()

    db_session.add(
        IdempotencyKey(
            merchant_id=merchant.id,
            key="create-link-1",
            operation="create_payment_link",
            request_hash="hash-a",
            status=IdempotencyKeyStatus.IN_PROGRESS,
        )
    )
    db_session.flush()
    db_session.add(
        IdempotencyKey(
            merchant_id=merchant.id,
            key="create-link-1",
            operation="create_payment_link",
            request_hash="hash-b",
            status=IdempotencyKeyStatus.IN_PROGRESS,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_idempotency_key_same_hash_can_be_completed(db_session) -> None:
    merchant = Merchant(name="Idempotency Merchant 2", slug="idempotency-merchant-2")
    db_session.add(merchant)
    db_session.flush()

    record = IdempotencyKey(
        merchant_id=merchant.id,
        key="refund-1",
        operation="refund_payment",
        request_hash="hash-refund",
        status=IdempotencyKeyStatus.COMPLETED,
        completed_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        response_reference="rfnd_123",
    )
    db_session.add(record)
    db_session.flush()
    loaded = db_session.get(IdempotencyKey, record.id)
    assert loaded is not None
    assert loaded.request_hash == "hash-refund"
    assert loaded.status == IdempotencyKeyStatus.COMPLETED
