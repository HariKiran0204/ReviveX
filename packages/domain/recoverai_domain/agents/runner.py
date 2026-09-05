from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from recoverai_domain.agents.config import SOURCE_LLM, AgentSettings
from recoverai_domain.agents.llm import LlmClient, LlmError, LlmRequest, parse_json_object
from recoverai_domain.agents.security import PromptBundle, render_user_message


def try_llm_model[T: BaseModel](
    *,
    client: LlmClient,
    settings: AgentSettings,
    prompt: PromptBundle,
    model_cls: type[T],
    policy_block: str,
    case_block: str,
    customer_block: str,
    extra: str = "",
    merge: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> T | None:
    request = LlmRequest(
        agent_name=prompt.name,
        system=f"{prompt.system}\n\n{prompt.constraints}",
        constraints=prompt.constraints,
        output_schema=prompt.output_schema,
        user=render_user_message(
            policy_block=policy_block,
            case_block=case_block,
            customer_block=customer_block,
            extra=extra,
        ),
        timeout_seconds=settings.llm_timeout_seconds,
    )
    attempts = settings.llm_max_retries + 1
    for _ in range(attempts):
        try:
            response = client.complete(request)
            payload = parse_json_object(response.text)
            if merge is not None:
                payload = merge(payload)
            return model_cls.model_validate(payload)
        except (LlmError, ValidationError, ValueError):
            continue
    return None


def attach_source(payload: dict[str, Any], *, version: str) -> dict[str, Any]:
    data = dict(payload)
    data["source"] = SOURCE_LLM
    data["agent_version"] = version
    return data
