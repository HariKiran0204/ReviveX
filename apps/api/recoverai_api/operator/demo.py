from __future__ import annotations

from decimal import Decimal
from time import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_api.config import Settings
from recoverai_api.events.schemas import IngestAcknowledgement
from recoverai_api.events.service import run_scenario
from recoverai_api.operator.merchant import resolve_merchant
from recoverai_db.models import RecoveryCase, WebhookEvent
from recoverai_domain.followups import apply_followups
from recoverai_domain.ingestion import EventQueue, IngestResult
from recoverai_domain.processing import process_webhook_event
from recoverai_domain.processor import RecoveryCaseProcessor, verify_recovery_case
from recoverai_domain.tools.execution import ToolExecutionService


def run_operator_demo(
    session: Session,
    queue: EventQueue,
    settings: Settings,
    *,
    kind: str,
    merchant_slug: str | None,
    seed: int | None,
    amount: Decimal | None,
) -> dict[str, Any]:
    resolved_seed = seed if seed is not None else int(time()) % 1_000_000
    key = kind.strip().lower()
    merchant = resolve_merchant(session, merchant_slug=merchant_slug, required=False)
    slug = merchant.slug if merchant is not None else merchant_slug

    if key in {"run_demo", "demo"}:
        acks = run_scenario(
            session,
            queue,
            scenario="A",
            settings=settings,
            merchant_slug=slug,
            seed=resolved_seed,
            amount=amount or Decimal("499.00"),
        )
        cases = _drain_and_process(session, queue, process_cases=True)
        return _demo_result("run_demo", acks, cases, extra={"seed": resolved_seed})

    if key in {"failed_payment", "create_failed_payment"}:
        acks = run_scenario(
            session,
            queue,
            scenario="A",
            settings=settings,
            merchant_slug=slug,
            seed=resolved_seed,
            amount=amount or Decimal("799.00"),
        )
        cases = _drain_and_process(session, queue, process_cases=False)
        return _demo_result("failed_payment", acks, cases, extra={"seed": resolved_seed})

    if key in {"approval", "create_approval"}:
        acks = run_scenario(
            session,
            queue,
            scenario="A",
            settings=settings,
            merchant_slug=slug,
            seed=resolved_seed,
            amount=amount or Decimal("40000.00"),
        )
        cases = _drain_and_process(session, queue, process_cases=True)
        return _demo_result("approval", acks, cases, extra={"seed": resolved_seed})

    if key in {"policy_block", "create_policy_block"}:
        acks = run_scenario(
            session,
            queue,
            scenario="A",
            settings=settings,
            merchant_slug=slug,
            seed=resolved_seed,
            amount=amount or Decimal("900.00"),
        )
        cases = _drain_and_process(session, queue, process_cases=False)
        executions = []
        for case in cases:
            RecoveryCaseProcessor(session).walk_to_policy_check(case)
            session.flush()
            result = ToolExecutionService(session).execute(
                case.id,
                action="OFFER_DISCOUNT",
                payload={"discount_percent": "50"},
                idempotency_key=f"demo-block-{resolved_seed}-{case.id}",
                merchant_id=case.merchant_id,
                actor_id="demo-operator",
            )
            executions.append(result.to_public_dict())
        return _demo_result(
            "policy_block",
            acks,
            cases,
            extra={"seed": resolved_seed, "executions": executions},
        )

    if key in {"verification_mismatch", "create_verification_mismatch"}:
        acks = run_scenario(
            session,
            queue,
            scenario="H",
            settings=settings,
            merchant_slug=slug,
            seed=resolved_seed,
            amount=amount or Decimal("1200.00"),
        )
        cases = _drain_and_process(session, queue, process_cases=True)
        verifications: list[dict[str, Any]] = []
        for case in cases:
            verifications.append(verify_recovery_case(session, case.id))
        return _demo_result(
            "verification_mismatch",
            acks,
            cases,
            extra={"seed": resolved_seed, "verifications": verifications},
        )

    if key in {"full_recovery", "successful_recovery"}:
        acks = run_scenario(
            session,
            queue,
            scenario="A",
            settings=settings,
            merchant_slug=slug,
            seed=resolved_seed,
            amount=amount or Decimal("499.00"),
        )
        cases = _drain_and_process(session, queue, process_cases=True)
        executions = []
        for case in cases:
            RecoveryCaseProcessor(session, settings).walk_to_policy_check(case)
            session.flush()
            result = ToolExecutionService(session, settings=settings, queue=queue).execute(
                case.id,
                action="RETRY_NOW",
                payload={"attempt_number": 1},
                idempotency_key=f"demo-full-{resolved_seed}-{case.id}",
                merchant_id=case.merchant_id,
                actor_id="demo-operator",
            )
            executions.append(result.to_public_dict())
        # Process the retry payment capture event and verification followup
        cases = _drain_and_process(session, queue, process_cases=True)
        return _demo_result(
            "full_recovery",
            acks,
            cases,
            extra={"seed": resolved_seed, "executions": executions},
        )

    if key in {"failed_recovery"}:
        acks = run_scenario(
            session,
            queue,
            scenario="A",
            settings=settings,
            merchant_slug=slug,
            seed=resolved_seed,
            amount=amount or Decimal("499.00"),
        )
        cases = _drain_and_process(session, queue, process_cases=True)
        executions = []
        for case in cases:
            RecoveryCaseProcessor(session, settings).walk_to_policy_check(case)
            session.flush()
            result = ToolExecutionService(session, settings=settings, queue=queue).execute(
                case.id,
                action="RETRY_NOW",
                payload={"attempt_number": 2},
                idempotency_key=f"demo-failed-{resolved_seed}-{case.id}",
                merchant_id=case.merchant_id,
                actor_id="demo-operator",
            )
            executions.append(result.to_public_dict())
        cases = _drain_and_process(session, queue, process_cases=True)
        return _demo_result(
            "failed_recovery",
            acks,
            cases,
            extra={"seed": resolved_seed, "executions": executions},
        )

    raise ValueError(f"Unknown demo kind: {kind}")


def _drain_and_process(
    session: Session,
    queue: EventQueue,
    *,
    process_cases: bool,
) -> list[RecoveryCase]:
    webhook_ids: list[UUID] = []
    enqueued = getattr(queue, "enqueued", None)
    if isinstance(enqueued, list):
        webhook_ids = list(enqueued)
        enqueued.clear()
    else:
        pending = list(
            session.scalars(
                select(WebhookEvent)
                .where(WebhookEvent.status == "RECEIVED")
                .order_by(WebhookEvent.received_at.asc())
            )
        )
        webhook_ids = [row.id for row in pending]
    case_ids: set[UUID] = set()
    for webhook_id in webhook_ids:
        result = process_webhook_event(session, webhook_id)
        followups = result.get("followups")
        if isinstance(followups, list):
            for item in followups:
                if isinstance(item, dict) and item.get("case_id"):
                    case_ids.add(UUID(str(item["case_id"])))
            if process_cases:
                apply_followups(session, followups)
    cases: list[RecoveryCase] = []
    for case_id in case_ids:
        loaded = session.get(RecoveryCase, case_id)
        if loaded is not None:
            cases.append(loaded)
    return cases


def _demo_result(
    kind: str,
    acks: list[IngestResult],
    cases: list[RecoveryCase],
    extra: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "acknowledgements": [
            IngestAcknowledgement(
                accepted=True,
                duplicate=item.duplicate,
                queued=item.queued,
                event_id=item.event_id,
                webhook_event_id=item.webhook_event_id,
                status=item.status,
                merchant_id=item.merchant_id,
                correlation_id=item.correlation_id,
            ).model_dump(mode="json")
            for item in acks
        ],
        "cases": [
            {
                "id": str(case.id),
                "status": case.status,
                "amount_at_risk": str(case.amount_at_risk),
                "amount_recovered": str(case.amount_recovered),
                "case_type": case.case_type,
            }
            for case in cases
        ],
        **extra,
    }
