from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recoverai_db.enums import RecoveryCaseStatus
from recoverai_db.models import Payment, RecoveryAction, RecoveryCase
from recoverai_domain.agents.config import ANALYST_VERSION, AgentSettings
from recoverai_domain.agents.fallbacks import fallback_analyst
from recoverai_domain.agents.llm import LlmClient, StubLlmClient
from recoverai_domain.agents.prompts.catalog import ANALYST_PROMPT
from recoverai_domain.agents.runner import attach_source, try_llm_model
from recoverai_domain.agents.schemas import AnalystAnswer
from recoverai_domain.money import ZERO


class RecoveryAnalystAgent:
    """Read-only merchant Q&A over prepared aggregates. No SQL for the LLM."""

    def __init__(self, settings: AgentSettings, llm: LlmClient | None = None) -> None:
        self._settings = settings
        self._llm = llm or StubLlmClient()

    def answer(self, session: Session, merchant_id: UUID, question: str) -> AnalystAnswer:
        metrics = merchant_aggregates(session, merchant_id)
        fallback = fallback_analyst(question, metrics)
        llm_result = try_llm_model(
            client=self._llm,
            settings=self._settings,
            prompt=ANALYST_PROMPT,
            model_cls=AnalystAnswer,
            policy_block="Read-only. Do not execute recovery actions.",
            case_block=str(metrics),
            customer_block="(no customer payload)",
            extra=f"Question: {question}",
            merge=lambda payload: {
                **attach_source(payload, version=ANALYST_VERSION),
                "question": question,
                "metrics": metrics,
            },
        )
        return llm_result if llm_result is not None else fallback


def merchant_aggregates(session: Session, merchant_id: UUID) -> dict[str, str]:
    at_risk = session.scalar(
        select(func.coalesce(func.sum(RecoveryCase.amount_at_risk), 0)).where(
            RecoveryCase.merchant_id == merchant_id,
            RecoveryCase.closed_at.is_(None),
        )
    )
    recovered = session.scalar(
        select(func.coalesce(func.sum(RecoveryCase.amount_recovered), 0)).where(
            RecoveryCase.merchant_id == merchant_id
        )
    )
    open_cases = session.scalar(
        select(func.count()).where(
            RecoveryCase.merchant_id == merchant_id,
            RecoveryCase.status != RecoveryCaseStatus.RECOVERED,
            RecoveryCase.closed_at.is_(None),
        )
    )
    top_failure_row = session.execute(
        select(Payment.failure_code)
        .where(Payment.merchant_id == merchant_id, Payment.failure_code.is_not(None))
        .group_by(Payment.failure_code)
        .order_by(func.count().desc())
        .limit(1)
    ).first()
    top_action_row = session.execute(
        select(RecoveryAction.action_type)
        .where(RecoveryAction.merchant_id == merchant_id)
        .group_by(RecoveryAction.action_type)
        .order_by(func.count().desc())
        .limit(1)
    ).first()
    recovered_dec = Decimal(str(recovered or 0))
    at_risk_dec = Decimal(str(at_risk or 0))
    rate = "0"
    if at_risk_dec > ZERO:
        rate = str((recovered_dec / at_risk_dec).quantize(Decimal("0.0001")))
    failure = str(top_failure_row[0]) if top_failure_row and top_failure_row[0] else ""
    action = str(top_action_row[0]) if top_action_row and top_action_row[0] else ""
    return {
        "revenue_at_risk": str(Decimal(str(at_risk or 0))),
        "revenue_recovered": str(recovered_dec),
        "expected_vs_actual": "metrics are ACTUAL recovered vs open at-risk, not ERV",
        "open_cases": str(int(open_cases or 0)),
        "recovery_rate": rate,
        "top_failure_reason": str(failure or ""),
        "top_intervention": str(action or ""),
    }
