# ADR-0007: Narrow agents on a deterministic control plane

**Status:** Accepted  
**Date:** 2026-09-04  
**Phase:** 8 — Multi-agent recovery orchestration

## Context

Phases 5–7 already provide policy, tools, calibrated probabilities, and
Expected Recovery Value. Phase 8 needs language models for triage, diagnosis,
and merchant-facing explanation without giving them the ability to invent
money, skip policy, or call a payment provider.

An unrestricted “recovery copilot” loop would mix reasoning with execution and
would not be evaluable.

## Decisions

### Multiple narrow agents

Each agent has one job and a versioned prompt (`triage-v1`, …). Structured
Pydantic outputs are required. Invalid JSON is rejected.

### Agents do not control money

ERV stays in `RecoveryOptimizer`. `amount_recovered` stays in
`RecoveryVerificationService`. Agents may only **read** `OptimizationResult`
and copy `selected_action` into an explanation.

### ML and ERV remain deterministic

Strategy proposes a closed-enum candidate set. Phase 6 scores probabilities.
Phase 7 ranks. The LLM is not an alternative optimizer.

### Policy is authoritative

Even if strategy prefers `OFFER_DISCOUNT`, a cap, kill switch, or opt-out still
blocks execution. Approval-required actions pause at `AWAITING_APPROVAL`.

### Bounded execution

`MAX_AGENT_STEPS` and `MAX_TOOL_CALLS` stop runaway loops. Limits audit and
escalate when the case is already in `POLICY_CHECK`.

### Stub LLM plus explicit fallback

The default provider is `stub`. Deterministic rules keep the pipeline alive.
`source` is `LLM` or `DETERMINISTIC_FALLBACK` — never mixed silently.

## Consequences

- Phase 9 can render explanations and agent runs in the operator UI.
- A later HTTP LLM adapter can implement `LlmClient` without changing money
  paths.
- Prompt injection in customer notes cannot mint actions or recovered revenue.

## Alternatives considered

- Single autonomous ReAct loop: rejected — unbounded tool use and unevaluable.
- LLM outputs a rupee ERV: rejected — ADR-0006.
- Agent calls `PaymentProvider`: rejected — ADR-0004.
- Crashing when the LLM is down: rejected — recovery must still triage.
