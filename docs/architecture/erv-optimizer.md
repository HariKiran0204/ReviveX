# Expected Recovery Value optimizer (Phase 7)

Phase 7 ranks legal recovery interventions by **Expected Recovery Value (ERV)**.
It does not execute tools, call `PaymentProvider`, or write `amount_recovered`.

Package: `packages/domain/recoverai_domain/optimizer/`

## Formula

All monetary terms are `Decimal` quantized to ₹0.01 (`signed_money` / `as_money`).
Probability is validated in `[0, 1]` and converted with `Decimal(str(p))` before
multiplication so binary floats never become money.

```
expected_recovery = P(recovery | case, action) × amount_at_risk

ERV = expected_recovery
    − intervention_cost
    − discount_cost
    − communication_cost
    − risk_penalty
```

`amount_at_risk` is the case exposure. `expected_recovery` is a probabilistic
forecast. **Actual recovered revenue** is created only by
`RecoveryVerificationService`.

Optimizer version: `erv-v1` (`OPTIMIZER_VERSION`). A later formula change must
use `erv-v2` so historical `recovery_decisions` remain interpretable.

## Cost model (prototype assumptions)

These are configurable demo costs in INR. They are **not** Razorpay fee tables.

| Action | Intervention | Communication | Risk penalty | Discount |
| --- | --- | --- | --- | --- |
| `RETRY_NOW` | 5.00 | 0 | 15.00 | 0 |
| `RETRY_LATER` | 2.00 | 0 | 4.00 | 0 |
| `SEND_PAYMENT_LINK` | 3.00 | 1.50 | 8.00 | 0 |
| `SEND_REMINDER` | 0.50 | 1.50 | 12.00 | 0 |
| `OFFER_DISCOUNT` | 1.00 | 1.50 | 40.00 | `amount_at_risk × percent / 100` |
| `ESCALATE` | 250.00 | 0 | 30.00 | 0 |
| `DO_NOTHING` | 0 | 0 | 0 | 0 |

Environment overrides: `COST_RETRY_NOW`, `COST_PAYMENT_LINK`,
`COST_HUMAN_ESCALATION`, `COST_*_COMMUNICATION`, `RISK_PENALTY_*`,
`DEFAULT_DISCOUNT_PERCENT` (default 5), `PREDICTION_TTL_MINUTES` (default 60),
`ERV_TIE_EPSILON` (default 0.01), `OPTIMIZER_VERSION`.

## Discount economics

For `OFFER_DISCOUNT`, discount cost is the concession on `amount_at_risk`.
Example: ₹4,000 at 5% → ₹200. Higher P(recovery) is compared against that
concession plus intervention, communication, and risk penalty. A higher
probability can still lose on net value.

## Candidate generation

The closed action enum is the candidate set:

`RETRY_NOW`, `RETRY_LATER`, `SEND_PAYMENT_LINK`, `SEND_REMINDER`,
`OFFER_DISCOUNT`, `ESCALATE`, `DO_NOTHING`

Recovery interventions: the first five. `ESCALATE` and `DO_NOTHING` are
control/reference strategies. The optimizer will not force a payment action
when every permitted recovery intervention has negative ERV.

## ML interaction

The optimizer calls Phase 6 `predict_recovery_probability(case_context, action)`.
It does not load sklearn artifacts. Sources are recorded as:

- `MODEL` (trained pipeline; eval package `source=ml`)
- `MODEL_FALLBACK` (deterministic simulator-rule score)
- `OVERRIDE` (tests / injected probabilities)

Stored `model_predictions` older than `PREDICTION_TTL_MINUTES` are not reused.
A fresh prediction is requested. Missing candidate probabilities exclude that
action from selection instead of inventing a score.

## Policy interaction

Recommended flow:

1. Generate legal candidates
2. Score P(recovery)
3. Calculate ERV
4. Evaluate each candidate with `PolicyEngine`
5. Drop blocked actions
6. Keep `requires_approval` on allowed high-value / YELLOW actions
7. Rank remaining valid actions
8. Select the highest-value **permitted** recovery intervention with ERV ≥ 0

`PolicyEngine` remains the authority on allow / approve / block. A winning ERV
that exceeds the merchant discount cap is blocked; the optimizer falls back to
the next legal action. Approval-required actions may still be **selected**; they
are not executed by this layer.

## Tie-breaking

If ERVs differ by at most `ERV_TIE_EPSILON` (default ₹0.01), the winner is the
first of:

1. Lower customer friction (`DO_NOTHING` < `RETRY_LATER` < `SEND_PAYMENT_LINK`
   < `SEND_REMINDER` < `RETRY_NOW` < `OFFER_DISCOUNT` < `ESCALATE`)
2. Lower direct cost (intervention + communication + discount)
3. Lower `risk_penalty`
4. Simpler action (`DO_NOTHING` < `SEND_REMINDER` < `RETRY_LATER` <
   `SEND_PAYMENT_LINK` < `RETRY_NOW` < `OFFER_DISCOUNT` < `ESCALATE`)
5. Lexicographic action name

Ranks are explicit tables, not Python dict iteration order.

## Negative ERV

If every permitted recovery intervention has ERV < 0, the optimizer selects
`DO_NOTHING`, or `ESCALATE` when the case is suspicious / source-mismatched
(and that control action is permitted). It does not pick the “least bad”
recovery action.

## Persistence

Each run **inserts** a `recovery_decisions` row (`decision_version=erv-v1`).
Historical rows are never updated. Payload includes candidates, probabilities,
costs, expected values, policy verdict, model version, and optimizer version.

## Batch / counterfactual

`optimize_batch` scores a list of case snapshots. It does not execute tools.
Phase 12 can use this for offline comparison.

## Read-only contract

`RecoveryOptimizer.optimize` / `optimize_case` return `OptimizationResult`.
They must not call providers or credit recovery. HTTP:
`POST /v1/recovery-cases/{id}/optimize`.

## Phase 9 handoff

Phase 9 should bind the operator UI to cases, ERV rankings, approvals, and
agent-run explanations. Do not let the UI write recovered revenue.
