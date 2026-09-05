from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from recoverai_db.enums import IdempotencyKeyStatus
from recoverai_db.models import IdempotencyKey
from recoverai_domain.errors import IdempotencyConflictError

IDEMPOTENCY_TTL_HOURS = 24

SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "secret",
    "api_key",
    "password",
    "card_number",
    "cvv",
    "pan",
    "token",
    "credential",
)


def canonical_request_hash(payload: dict[str, Any]) -> str:
    cleaned = sanitize_payload(payload)
    encoded = json.dumps(cleaned, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS):
                continue
            result[str(key)] = sanitize_payload(item)
        return result
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    return value


class IdempotencyOutcome:
    def __init__(
        self,
        record: IdempotencyKey,
        *,
        replay: bool,
    ) -> None:
        self.record = record
        self.replay = replay


def begin_idempotent_operation(
    session: Session,
    *,
    merchant_id: UUID,
    key: str,
    operation: str,
    request_hash: str,
) -> IdempotencyOutcome:
    existing = session.scalar(
        select(IdempotencyKey)
        .where(IdempotencyKey.merchant_id == merchant_id, IdempotencyKey.key == key)
        .with_for_update()
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(key)
        return IdempotencyOutcome(existing, replay=True)

    record = IdempotencyKey(
        merchant_id=merchant_id,
        key=key,
        operation=operation,
        request_hash=request_hash,
        status=IdempotencyKeyStatus.IN_PROGRESS,
        expires_at=datetime.now(UTC) + timedelta(hours=IDEMPOTENCY_TTL_HOURS),
        metadata_json={},
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError:
        raced = session.scalar(
            select(IdempotencyKey)
            .where(IdempotencyKey.merchant_id == merchant_id, IdempotencyKey.key == key)
            .with_for_update()
        )
        if raced is None:
            raise
        if raced.request_hash != request_hash:
            raise IdempotencyConflictError(key) from None
        return IdempotencyOutcome(raced, replay=True)
    return IdempotencyOutcome(record, replay=False)


def complete_idempotent_operation(
    record: IdempotencyKey,
    *,
    response: dict[str, Any],
    response_reference: str | None,
) -> None:
    record.status = IdempotencyKeyStatus.COMPLETED
    record.completed_at = datetime.now(UTC)
    record.response_reference = response_reference
    metadata = dict(record.metadata_json or {})
    metadata["result"] = response
    record.metadata_json = metadata


def fail_idempotent_operation(record: IdempotencyKey, *, error_code: str) -> None:
    record.status = IdempotencyKeyStatus.FAILED
    record.completed_at = datetime.now(UTC)
    metadata = dict(record.metadata_json or {})
    metadata["error_code"] = error_code
    record.metadata_json = metadata
