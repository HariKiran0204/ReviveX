from __future__ import annotations

from typing import Any

from recoverai_db.enums import RecoveryActionType
from recoverai_eval.errors import ModelQualityError
from recoverai_providers.models import FailureReason


def directional_recovery_checks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Statistical checks on labeled data. No row-level 'action X always wins'."""

    def rate(failure: str, action: str) -> float | None:
        matched = [
            int(row["recovered"])
            for row in rows
            if row.get("failure_reason") == failure and row.get("action") == action
        ]
        if len(matched) < 20:
            return None
        return sum(matched) / len(matched)

    bank_retry = rate(FailureReason.TEMPORARY_BANK_ERROR.value, RecoveryActionType.RETRY_NOW.value)
    expired_retry = rate(FailureReason.EXPIRED_CARD.value, RecoveryActionType.RETRY_NOW.value)
    expired_link = rate(
        FailureReason.EXPIRED_CARD.value, RecoveryActionType.SEND_PAYMENT_LINK.value
    )
    funds_now = rate(FailureReason.INSUFFICIENT_FUNDS.value, RecoveryActionType.RETRY_NOW.value)
    funds_later = rate(FailureReason.INSUFFICIENT_FUNDS.value, RecoveryActionType.RETRY_LATER.value)
    checks: dict[str, Any] = {
        "temp_bank_retry_gt_expired_retry": {
            "ok": bank_retry is not None
            and expired_retry is not None
            and bank_retry > expired_retry,
            "temp_bank_retry": bank_retry,
            "expired_retry": expired_retry,
        },
        "expired_link_gt_expired_retry": {
            "ok": expired_link is not None
            and expired_retry is not None
            and expired_link > expired_retry,
            "expired_link": expired_link,
            "expired_retry": expired_retry,
        },
        "funds_later_gt_funds_now": {
            "ok": funds_later is not None and funds_now is not None and funds_later > funds_now,
            "funds_later": funds_later,
            "funds_now": funds_now,
        },
    }
    return checks


def assert_directional_labels(rows: list[dict[str, Any]]) -> None:
    checks = directional_recovery_checks(rows)
    failed = [name for name, payload in checks.items() if payload["ok"] is not True]
    if failed:
        raise ModelQualityError(
            "BUSINESS_SENSE",
            f"Labeled data failed directional checks: {failed} ({checks})",
        )


def directional_prediction_checks(
    rows: list[dict[str, Any]],
    y_prob: list[float],
) -> dict[str, Any]:
    def mean_p(failure: str, action: str) -> float | None:
        matched = [
            prob
            for row, prob in zip(rows, y_prob, strict=True)
            if row.get("failure_reason") == failure and row.get("action") == action
        ]
        if len(matched) < 10:
            return None
        return sum(matched) / len(matched)

    bank_retry = mean_p(
        FailureReason.TEMPORARY_BANK_ERROR.value, RecoveryActionType.RETRY_NOW.value
    )
    expired_retry = mean_p(FailureReason.EXPIRED_CARD.value, RecoveryActionType.RETRY_NOW.value)
    expired_link = mean_p(
        FailureReason.EXPIRED_CARD.value, RecoveryActionType.SEND_PAYMENT_LINK.value
    )
    funds_now = mean_p(FailureReason.INSUFFICIENT_FUNDS.value, RecoveryActionType.RETRY_NOW.value)
    funds_later = mean_p(
        FailureReason.INSUFFICIENT_FUNDS.value, RecoveryActionType.RETRY_LATER.value
    )
    return {
        "temp_bank_retry_gt_expired_retry": {
            "ok": bank_retry is not None
            and expired_retry is not None
            and bank_retry > expired_retry,
            "temp_bank_retry": bank_retry,
            "expired_retry": expired_retry,
        },
        "expired_link_gt_expired_retry": {
            "ok": expired_link is not None
            and expired_retry is not None
            and expired_link > expired_retry,
            "expired_link": expired_link,
            "expired_retry": expired_retry,
        },
        "funds_later_gt_funds_now": {
            "ok": funds_later is not None and funds_now is not None and funds_later > funds_now,
            "funds_later": funds_later,
            "funds_now": funds_now,
        },
    }
