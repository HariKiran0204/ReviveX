from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.enums import ActorType, AgentRunStatus
from recoverai_db.models import AgentRun
from recoverai_domain.agents.security import strip_secrets
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit


def start_agent_run(
    session: Session,
    *,
    merchant_id: UUID,
    case_id: UUID | None,
    agent_name: str,
    agent_version: str,
    input_summary: dict[str, Any],
    correlation_id: str | None = None,
) -> tuple[AgentRun, float]:
    now = datetime.now(UTC)
    row = AgentRun(
        merchant_id=merchant_id,
        recovery_case_id=case_id,
        agent_name=agent_name,
        agent_version=agent_version,
        status=AgentRunStatus.RUNNING,
        input_summary=strip_secrets(input_summary),
        started_at=now,
    )
    session.add(row)
    session.flush()
    record_audit(
        session,
        merchant_id=merchant_id,
        case_id=case_id,
        event_type=AuditEventType.AGENT_RUN_RECORDED,
        summary=f"Started {agent_name} {agent_version}",
        actor_type=ActorType.AGENT,
        action=agent_name,
        correlation_id=correlation_id,
        metadata={"agent_run_id": str(row.id), "agent_version": agent_version},
    )
    return row, perf_counter()


def complete_agent_run(
    session: Session,
    row: AgentRun,
    *,
    started: float,
    output_summary: dict[str, Any],
    source: str,
    status: str = AgentRunStatus.COMPLETED,
    error_message: str | None = None,
    correlation_id: str | None = None,
) -> AgentRun:
    now = datetime.now(UTC)
    row.status = status
    row.output_summary = strip_secrets(output_summary)
    row.decision_factors = {"source": source, "agent_version": row.agent_version}
    row.error_message = error_message
    row.completed_at = now
    row.latency_ms = int((perf_counter() - started) * 1000)
    session.flush()
    record_audit(
        session,
        merchant_id=row.merchant_id,
        case_id=row.recovery_case_id,
        event_type=AuditEventType.AGENT_RUN_RECORDED,
        summary=f"Finished {row.agent_name} source={source} status={status}",
        actor_type=ActorType.AGENT,
        action=row.agent_name,
        correlation_id=correlation_id,
        metadata={
            "agent_run_id": str(row.id),
            "source": source,
            "latency_ms": row.latency_ms,
            "status": status,
        },
    )
    return row
