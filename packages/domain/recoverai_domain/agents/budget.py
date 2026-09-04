from __future__ import annotations

from recoverai_domain.agents.config import AgentSettings
from recoverai_domain.errors import AgentError


class ExecutionBudget:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.steps = 0
        self.tool_calls = 0
        self.tool_counts: dict[str, int] = {}

    def add_step(self, name: str) -> None:
        self.steps += 1
        if self.steps > self.settings.max_agent_steps:
            raise AgentError(
                "AGENT_STEP_LIMIT",
                f"Exceeded MAX_AGENT_STEPS={self.settings.max_agent_steps} at {name}",
            )

    def add_tool(self, tool_name: str) -> None:
        self.tool_calls += 1
        self.tool_counts[tool_name] = self.tool_counts.get(tool_name, 0) + 1
        if self.tool_calls > self.settings.max_tool_calls:
            raise AgentError(
                "AGENT_TOOL_LIMIT",
                f"Exceeded MAX_TOOL_CALLS={self.settings.max_tool_calls}",
            )
        if self.tool_counts[tool_name] > self.settings.max_repeated_tool_calls:
            raise AgentError(
                "AGENT_REPEATED_TOOL_LIMIT",
                f"Tool {tool_name} exceeded repeated-call limit",
            )
