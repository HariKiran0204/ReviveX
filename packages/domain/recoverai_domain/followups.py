from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_domain.processor import process_recovery_case, verify_recovery_case


def apply_followups(session: Session, followups: object) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    if not isinstance(followups, list):
        return results
    for item in followups:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        case_raw = item.get("case_id")
        if not isinstance(case_raw, str):
            continue
        case_id = UUID(case_raw)
        payment_raw = item.get("payment_id")
        webhook_raw = item.get("webhook_event_id")
        payment_id = UUID(payment_raw) if isinstance(payment_raw, str) else None
        webhook_event_id = UUID(webhook_raw) if isinstance(webhook_raw, str) else None
        if name == "process_recovery_case":
            results.append(dict(process_recovery_case(session, case_id)))
        elif name == "verify_recovery_case":
            results.append(
                dict(
                    verify_recovery_case(
                        session,
                        case_id,
                        payment_id=payment_id,
                        webhook_event_id=webhook_event_id,
                    )
                )
            )
    return results
