# ADR-0006: Deterministic Expected Recovery Value optimization

**Status:** Accepted  
**Date:** 2026-09-04  
**Phase:** 7 — Expected Recovery Value optimizer

## Context

Phase 6 produces calibrated `P(recovery | case, action)`. Phase 5 already
decides whether an action is allowed and whether a human must approve it.
Someone still has to turn those probabilities into a **ranking** of
interventions: retry now, send a link, offer a discount, or do nothing.

If an LLM (or the classifier itself) picked the action, money arithmetic would
be uninspectable, costs would drift, and policy could be talked around. Recovered
revenue would also be easy to confuse with a forecast.

## Decisions

### ERV is deterministic Python

Expected Recovery Value is a closed formula over `Decimal` costs and a
unit-interval probability. The same case, candidates, probabilities, policy
results, and settings always yield the same ranking. Tie-breaking uses explicit
friction / cost / risk / simplicity ranks, not container iteration order.

### The LLM does not calculate money

Language models reason about context. They do not multiply rupees. Phase 8
agents may consume `OptimizationResult`; they must not invent expected value,
discount cost, or recovered revenue. Tools remain the only side-effect path
(ADR-0004).

### Policy remains authoritative

The optimizer proposes a ranking. `PolicyEngine.evaluate_action` still decides
allow / approve / block. A commercially attractive discount that exceeds the
merchant cap is not executed by winning ERV. Approval-required actions can be
selected and still wait for a human before `ToolExecutionService` runs.

### Expected revenue is not verified revenue

`expected_recovery = P × amount_at_risk` is a forecast. `amount_recovered` is
written only by `RecoveryVerificationService` after a matching capture
(ADR-0003). The optimizer never mutates that column and never calls
`PaymentProvider`.

### Fallback and freshness are explicit

Missing models use Phase 6 `MODEL_FALLBACK` and record `prediction_source`.
Stale `model_predictions` (configurable TTL) trigger a new inference call
instead of silently ranking on old odds.

## Consequences

- `recovery_decisions` stores versioned rankings (`erv-v1`) without overwriting
  history.
- Phase 8 can add agents on top of a ranked, policy-filtered action list.
- Prototype INR cost assumptions stay in `OptimizerSettings` and must not be
  presented as Razorpay’s fee schedule.

## Alternatives considered

- Argmax of P(recovery) without costs: rejected — discounts would always win.
- Letting the LLM output a rupee value: rejected — non-deterministic money.
- Optimizer executing the winning tool: rejected — bypasses idempotency,
  approval, and verification.
- Treating ERV as actual recovery in metrics: rejected — ADR-0003.
