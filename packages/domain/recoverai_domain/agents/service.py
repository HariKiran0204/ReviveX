from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_domain.agents.config import AgentSettings, load_agent_settings
from recoverai_domain.agents.llm import LlmClient
from recoverai_domain.agents.orchestrator import RecoveryAgentOrchestrator
from recoverai_domain.agents.schemas import AnalystAnswer, OrchestrationResult
from recoverai_domain.optimizer.service import RecoveryOptimizer
from recoverai_domain.tools.execution import ToolExecutionService


class RecoveryAgentService:
    def __init__(
        self,
        session: Session,
        *,
        settings: AgentSettings | None = None,
        llm: LlmClient | None = None,
        optimizer: RecoveryOptimizer | None = None,
        tools: ToolExecutionService | None = None,
    ) -> None:
        self._orchestrator = RecoveryAgentOrchestrator(
            session,
            settings=settings or load_agent_settings(),
            llm=llm,
            optimizer=optimizer,
            tools=tools,
        )

    def run_case(
        self,
        case_id: UUID,
        merchant_id: UUID | None = None,
        *,
        execute: bool = True,
        correlation_id: str | None = None,
    ) -> OrchestrationResult:
        return self._orchestrator.run_case(
            case_id,
            merchant_id,
            execute=execute,
            correlation_id=correlation_id,
        )

    def ask_analyst(self, merchant_id: UUID, question: str) -> AnalystAnswer:
        return self._orchestrator.ask_analyst(merchant_id, question)
