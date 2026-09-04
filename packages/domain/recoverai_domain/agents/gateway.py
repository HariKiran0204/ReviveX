from __future__ import annotations

from typing import Any
from uuid import UUID

from recoverai_db.enums import ActorType
from recoverai_domain.agents.budget import ExecutionBudget
from recoverai_domain.agents.config import READ_TOOLS
from recoverai_domain.errors import AgentError
from recoverai_domain.tools.execution import ToolExecutionResult, ToolExecutionService


class AgentToolGateway:
    """Agents may only reach side effects through ToolExecutionService."""

    def __init__(self, tools: ToolExecutionService, budget: ExecutionBudget) -> None:
        self._tools = tools
        self._budget = budget

    def execute(
        self,
        case_id: UUID,
        *,
        tool_name: str,
        action: str | None,
        payload: dict[str, Any],
        idempotency_key: str,
        merchant_id: UUID,
        correlation_id: str | None,
        allow_side_effect: bool,
    ) -> ToolExecutionResult:
        if not allow_side_effect and tool_name not in READ_TOOLS:
            raise AgentError(
                "TOOL_NOT_ALLOWED",
                f"Agent cannot call side-effect tool {tool_name} in this stage",
            )
        self._budget.add_tool(tool_name)
        return self._tools.execute(
            case_id,
            tool_name=tool_name,
            action=action,
            payload=payload,
            idempotency_key=idempotency_key,
            merchant_id=merchant_id,
            actor_type=ActorType.AGENT,
            actor_id="recovery-orchestrator",
            correlation_id=correlation_id,
        )
