from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.enums import ActorType, AgentRunStatus, RecoveryActionType, RecoveryCaseStatus
from recoverai_db.models import RecoveryCase
from recoverai_domain.agents.analyst import RecoveryAnalystAgent
from recoverai_domain.agents.budget import ExecutionBudget
from recoverai_domain.agents.config import (
    DIAGNOSIS_VERSION,
    EXPLAINER_VERSION,
    ORCHESTRATOR_VERSION,
    SOURCE_FALLBACK,
    STRATEGY_VERSION,
    TRIAGE_VERSION,
    AgentSettings,
    load_agent_settings,
)
from recoverai_domain.agents.context import RecoveryAgentContext, build_agent_context
from recoverai_domain.agents.explainers import (
    DecisionExplanationAgent,
    VerificationExplanationAgent,
)
from recoverai_domain.agents.gateway import AgentToolGateway
from recoverai_domain.agents.llm import LlmClient, StubLlmClient
from recoverai_domain.agents.persist import complete_agent_run, start_agent_run
from recoverai_domain.agents.schemas import AnalystAnswer, OrchestrationResult
from recoverai_domain.agents.specialists import DiagnosisAgent, RevenueTriageAgent, StrategyAgent
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.errors import AgentError, DomainError
from recoverai_domain.optimizer.service import RecoveryOptimizer
from recoverai_domain.optimizer.types import OptimizationResult
from recoverai_domain.state_machine import coerce_status, is_terminal
from recoverai_domain.tools.execution import ToolExecutionService
from recoverai_domain.tools.permissions import tool_for_action
from recoverai_domain.transitions import lock_recovery_case, transition_case

_STAGE_VERSIONS = {
    "triage": TRIAGE_VERSION,
    "diagnosis": DIAGNOSIS_VERSION,
    "strategy": STRATEGY_VERSION,
    "decision_explainer": EXPLAINER_VERSION,
}

_STAGE_ORDER = [
    RecoveryCaseStatus.DETECTED,
    RecoveryCaseStatus.TRIAGED,
    RecoveryCaseStatus.INVESTIGATING,
    RecoveryCaseStatus.DIAGNOSED,
    RecoveryCaseStatus.SCORING,
    RecoveryCaseStatus.STRATEGY_SELECTED,
    RecoveryCaseStatus.POLICY_CHECK,
]


class RecoveryAgentOrchestrator:
    """Bounded recovery stages. Not an unrestricted agent loop."""

    def __init__(
        self,
        session: Session,
        *,
        settings: AgentSettings | None = None,
        llm: LlmClient | None = None,
        optimizer: RecoveryOptimizer | None = None,
        tools: ToolExecutionService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or load_agent_settings()
        self._llm = llm or StubLlmClient()
        self._optimizer = optimizer or RecoveryOptimizer()
        self._tools = tools or ToolExecutionService(session)
        self._triage = RevenueTriageAgent(self._settings, self._llm)
        self._diagnosis = DiagnosisAgent(self._settings, self._llm)
        self._strategy = StrategyAgent(self._settings, self._llm)
        self._explainer = DecisionExplanationAgent(self._settings, self._llm)
        self._verify_explainer = VerificationExplanationAgent(self._settings, self._llm)
        self._analyst = RecoveryAnalystAgent(self._settings, self._llm)

    def run_case(
        self,
        case_id: UUID,
        merchant_id: UUID | None = None,
        *,
        execute: bool = True,
        correlation_id: str | None = None,
    ) -> OrchestrationResult:
        case = lock_recovery_case(self._session, case_id)
        if merchant_id is not None and case.merchant_id != merchant_id:
            raise DomainError("MERCHANT_MISMATCH", "Case does not belong to this merchant")
        if is_terminal(case.status):
            raise AgentError("CASE_TERMINAL", "Terminal cases are not orchestrated")
        recovered_before = case.amount_recovered
        budget = ExecutionBudget(self._settings)
        gateway = AgentToolGateway(self._tools, budget)
        fallbacks: list[str] = []
        orch, started = start_agent_run(
            self._session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            agent_name="orchestrator",
            agent_version=ORCHESTRATOR_VERSION,
            input_summary={"execute": execute},
            correlation_id=correlation_id,
        )
        try:
            context = build_agent_context(self._session, case)
            budget.add_step("triage")
            triage = self._persist_stage(
                case, "triage", lambda: self._triage.run(context), correlation_id
            )
            if triage.source == SOURCE_FALLBACK:
                fallbacks.append("triage")
            self._advance(case, RecoveryCaseStatus.TRIAGED, "Triage complete", correlation_id)

            budget.add_step("diagnosis")
            diagnosis = self._persist_stage(
                case, "diagnosis", lambda: self._diagnosis.run(context), correlation_id
            )
            if diagnosis.source == SOURCE_FALLBACK:
                fallbacks.append("diagnosis")
            self._advance(case, RecoveryCaseStatus.INVESTIGATING, "Investigating", correlation_id)
            self._advance(case, RecoveryCaseStatus.DIAGNOSED, "Diagnosis recorded", correlation_id)

            budget.add_step("strategy")
            strategy = self._persist_stage(
                case,
                "strategy",
                lambda: self._strategy.run(context, diagnosis),
                correlation_id,
            )
            if strategy.source == SOURCE_FALLBACK:
                fallbacks.append("strategy")

            budget.add_step("optimize")
            optimization = self._optimizer.optimize_case(
                self._session,
                case.id,
                persist=True,
                correlation_id=correlation_id,
                candidates=strategy.candidate_actions,
            )
            self._advance(case, RecoveryCaseStatus.SCORING, "ERV scoring", correlation_id)
            self._advance(
                case, RecoveryCaseStatus.STRATEGY_SELECTED, "Strategy selected", correlation_id
            )
            self._advance(case, RecoveryCaseStatus.POLICY_CHECK, "Policy check", correlation_id)

            budget.add_step("explain")
            explanation = self._explainer.run(context, optimization)
            if explanation.selected_action != optimization.selected_action:
                explanation = self._explainer.run(context, optimization)
            if explanation.source == SOURCE_FALLBACK:
                fallbacks.append("explainer")
            self._persist_stage(case, "decision_explainer", lambda: explanation, correlation_id)

            execution_status = None
            approval_id = None
            if execute and optimization.selected_action:
                budget.add_step("execute")
                tool_result = self._execute_selected(
                    gateway,
                    case,
                    optimization,
                    orch.id,
                    correlation_id,
                )
                execution_status = tool_result.status
                approval_id = str(tool_result.approval_id) if tool_result.approval_id else None

            self._session.refresh(case)
            if case.amount_recovered != recovered_before:
                raise AgentError(
                    "AGENT_MUTATED_RECOVERY",
                    "Agents must not write amount_recovered",
                )
            result = OrchestrationResult(
                case_id=str(case.id),
                merchant_id=str(case.merchant_id),
                case_status=case.status,
                triage=triage,
                diagnosis=diagnosis,
                strategy=strategy,
                selected_action=optimization.selected_action,
                selected_expected_value=(
                    str(optimization.selected_expected_value)
                    if optimization.selected_expected_value is not None
                    else None
                ),
                requires_approval=optimization.requires_approval,
                explanation=explanation,
                execution_status=execution_status,
                approval_id=approval_id,
                optimization=optimization.to_public_dict(),
                steps_used=budget.steps,
                tool_calls_used=budget.tool_calls,
                orchestrator_run_id=str(orch.id),
                amount_recovered=str(case.amount_recovered),
                fallbacks=fallbacks,
            )
            complete_agent_run(
                self._session,
                orch,
                started=started,
                output_summary=result.to_public_dict(),
                source=SOURCE_FALLBACK if fallbacks else "LLM",
                correlation_id=correlation_id,
            )
            return result
        except AgentError as exc:
            complete_agent_run(
                self._session,
                orch,
                started=started,
                output_summary={"error": exc.code},
                source=SOURCE_FALLBACK,
                status=AgentRunStatus.FAILED,
                error_message=exc.message,
                correlation_id=correlation_id,
            )
            if exc.code in {"AGENT_STEP_LIMIT", "AGENT_TOOL_LIMIT", "AGENT_REPEATED_TOOL_LIMIT"}:
                record_audit(
                    self._session,
                    merchant_id=case.merchant_id,
                    case_id=case.id,
                    event_type=AuditEventType.AGENT_LIMIT_EXCEEDED,
                    summary=exc.message,
                    actor_type=ActorType.AGENT,
                    correlation_id=correlation_id,
                    metadata={"code": exc.code},
                )
                self._fail_closed(case, correlation_id)
            raise

    def ask_analyst(self, merchant_id: UUID, question: str) -> AnalystAnswer:
        return self._analyst.answer(self._session, merchant_id, question)

    def explain_verification(
        self,
        context: RecoveryAgentContext,
        *,
        matched: bool,
        mismatch_reason: str | None,
        amount_recovered: str,
    ) -> Any:
        return self._verify_explainer.run(
            matched=matched,
            mismatch_reason=mismatch_reason,
            amount_recovered=amount_recovered,
            context=context,
        )

    def _persist_stage(
        self,
        case: RecoveryCase,
        name: str,
        fn: Any,
        correlation_id: str | None,
    ) -> Any:
        row, started = start_agent_run(
            self._session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            agent_name=name,
            agent_version=_STAGE_VERSIONS.get(name, ORCHESTRATOR_VERSION),
            input_summary={"case_id": str(case.id)},
            correlation_id=correlation_id,
        )
        output = fn()
        payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else dict(output)
        complete_agent_run(
            self._session,
            row,
            started=started,
            output_summary=payload,
            source=str(payload.get("source") or SOURCE_FALLBACK),
            correlation_id=correlation_id,
        )
        return output

    def _advance(
        self,
        case: RecoveryCase,
        target: RecoveryCaseStatus,
        summary: str,
        correlation_id: str | None,
    ) -> None:
        current = coerce_status(case.status)
        if current is target or _already_past(current, target):
            return
        if current is RecoveryCaseStatus.POLICY_CHECK:
            return
        if current in {
            RecoveryCaseStatus.AWAITING_APPROVAL,
            RecoveryCaseStatus.EXECUTING,
            RecoveryCaseStatus.ACTION_COMPLETED,
        }:
            return
        transition_case(
            self._session,
            case,
            target,
            actor_type=ActorType.AGENT,
            correlation_id=correlation_id,
            summary=summary,
        )

    def _execute_selected(
        self,
        gateway: AgentToolGateway,
        case: RecoveryCase,
        optimization: OptimizationResult,
        run_id: UUID,
        correlation_id: str | None,
    ) -> Any:
        action = optimization.selected_action
        if action is None:
            raise AgentError("NO_SELECTED_ACTION", "Optimizer did not select an action")
        tool_name = tool_for_action(action)
        if tool_name is None:
            raise AgentError("UNKNOWN_TOOL", f"No tool for {action}")
        payload = _payload_for_action(action, optimization)
        return gateway.execute(
            case.id,
            tool_name=tool_name,
            action=action,
            payload=payload,
            idempotency_key=f"agent:{run_id}:{action}",
            merchant_id=case.merchant_id,
            correlation_id=correlation_id,
            allow_side_effect=True,
        )

    def _fail_closed(self, case: RecoveryCase, correlation_id: str | None) -> None:
        current = coerce_status(case.status)
        if current is RecoveryCaseStatus.POLICY_CHECK:
            transition_case(
                self._session,
                case,
                RecoveryCaseStatus.ESCALATED,
                actor_type=ActorType.AGENT,
                correlation_id=correlation_id,
                summary="Agent limits exceeded; case escalated",
            )


def _payload_for_action(action: str, optimization: OptimizationResult) -> dict[str, Any]:
    if action == RecoveryActionType.RETRY_LATER.value:
        when = datetime.now(UTC) + timedelta(hours=1)
        return {"scheduled_for": when.isoformat()}
    if action == RecoveryActionType.OFFER_DISCOUNT.value:
        match = next(
            (item for item in optimization.candidate_actions if item.action == action),
            None,
        )
        percent = match.discount_percent if match is not None else None
        return {"discount_percent": str(percent or "5")}
    if action == RecoveryActionType.SEND_REMINDER.value:
        return {"channel": "EMAIL", "subject": "Payment reminder"}
    if action == RecoveryActionType.ESCALATE.value:
        return {"reason": "Orchestrator selected ESCALATE"}
    if action == RecoveryActionType.DO_NOTHING.value:
        return {"reason": "Orchestrator selected DO_NOTHING"}
    return {}


def _already_past(current: RecoveryCaseStatus, target: RecoveryCaseStatus) -> bool:
    try:
        return _STAGE_ORDER.index(current) > _STAGE_ORDER.index(target)
    except ValueError:
        return False
