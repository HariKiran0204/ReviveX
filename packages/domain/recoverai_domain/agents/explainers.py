from __future__ import annotations

from typing import Any

from recoverai_domain.agents.config import (
    EXPLAINER_VERSION,
    VERIFICATION_EXPLAINER_VERSION,
    AgentSettings,
)
from recoverai_domain.agents.context import RecoveryAgentContext
from recoverai_domain.agents.fallbacks import fallback_explanation, fallback_verification
from recoverai_domain.agents.llm import LlmClient, StubLlmClient
from recoverai_domain.agents.prompts.catalog import EXPLAINER_PROMPT, VERIFICATION_PROMPT
from recoverai_domain.agents.runner import attach_source, try_llm_model
from recoverai_domain.agents.schemas import DecisionExplanation, VerificationExplanation
from recoverai_domain.optimizer.types import OptimizationResult


class DecisionExplanationAgent:
    """Reads OptimizationResult. Cannot change selected_action."""

    def __init__(self, settings: AgentSettings, llm: LlmClient | None = None) -> None:
        self._settings = settings
        self._llm = llm or StubLlmClient()

    def run(
        self, context: RecoveryAgentContext, optimization: OptimizationResult
    ) -> DecisionExplanation:
        fallback = fallback_explanation(context, optimization)

        def merge(payload: dict[str, Any]) -> dict[str, Any]:
            data = attach_source(payload, version=EXPLAINER_VERSION)
            data["selected_action"] = optimization.selected_action
            data["reason"] = optimization.selection_reason
            return data

        llm_result = try_llm_model(
            client=self._llm,
            settings=self._settings,
            prompt=EXPLAINER_PROMPT,
            model_cls=DecisionExplanation,
            policy_block=str(context.policy_summary),
            case_block=str(optimization.to_public_dict()),
            customer_block=context.customer_untrusted_text,
            extra="Copy selected_action from OptimizationResult. Do not recompute ERV.",
            merge=merge,
        )
        if llm_result is None:
            return fallback
        if llm_result.selected_action != optimization.selected_action:
            return fallback
        return llm_result


class VerificationExplanationAgent:
    def __init__(self, settings: AgentSettings, llm: LlmClient | None = None) -> None:
        self._settings = settings
        self._llm = llm or StubLlmClient()

    def run(
        self,
        *,
        matched: bool,
        mismatch_reason: str | None,
        amount_recovered: str,
        context: RecoveryAgentContext,
    ) -> VerificationExplanation:
        fallback = fallback_verification(
            matched=matched,
            mismatch_reason=mismatch_reason,
            amount_recovered=amount_recovered,
        )
        llm_result = try_llm_model(
            client=self._llm,
            settings=self._settings,
            prompt=VERIFICATION_PROMPT,
            model_cls=VerificationExplanation,
            policy_block="Verification is authoritative. Do not change amounts.",
            case_block=str(
                {
                    "matched": matched,
                    "mismatch_reason": mismatch_reason,
                    "amount_recovered": amount_recovered,
                    "case": context.case,
                }
            ),
            customer_block=context.customer_untrusted_text,
            merge=lambda payload: attach_source(payload, version=VERIFICATION_EXPLAINER_VERSION),
        )
        return llm_result if llm_result is not None else fallback
