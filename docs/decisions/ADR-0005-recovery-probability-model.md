# ADR-0005: Action-conditioned recovery probability model

**Status:** Accepted  
**Date:** 2026-09-04  
**Phase:** 6 — Recovery probability model

## Context

Phase 5 can evaluate policy and execute registered tools, but it has no estimate of
whether a given intervention will actually recover revenue. Phase 7 needs
**calibrated** P(recovery | case, action) to compute Expected Recovery Value.
Agents must not be the first layer that invents recovery odds.

The model must not choose the action, must not call the payment provider, and must
not write `amount_recovered` (ADR-0003, ADR-0004).

## Decisions

### Probability is action-conditioned

Training rows are **case features + candidate action → recovered**. The same case
can have different probabilities for `RETRY_NOW` vs `SEND_PAYMENT_LINK`. A
context-only classifier would be useless to an ERV optimizer that compares
interventions.

### ML does not choose the action

The eval package returns a probability (and version metadata). Policy, approval,
and tools remain the execution path. Ranking and discount economics wait for
Phase 7.

### Calibrated probabilities matter for financial optimization

ERV multiplies probability by value (and later cost). Overconfident scores would
systematically over-retry or over-discount. Models are isotonic-calibrated on a
validation split. Selection uses Brier score, not accuracy. Held-out ROC-AUC,
PR-AUC, Brier, and calibration curves are mandatory before a version can be
marked production.

### Model failure falls back safely

Missing or corrupt artifacts yield a deterministic rule score labeled
`MODEL_FALLBACK`. The application keeps running. Callers must not treat the
fallback as a trained model version.

### Held-out evaluation is mandatory

Customers are partitioned so no customer appears in both train and test.
Evaluation never passes `recovered` (or other outcome fields) into inference.
Quality gates refuse to publish a production pointer when leakage, invalid
probabilities, or collapsed metrics are detected.

### Simulator labels, one engine

Outcomes are sampled from an extension of the existing simulator
(`intervention_recovery_probability`), not from a second unrelated Monte Carlo.
No action is forced to always succeed.

## Consequences

- `calculate_recovery_probability` can persist `model_predictions` without
  mutating recovery accounting.
- Phase 7 can score every legal action independently.
- Production PSP data can later replace synthetic labels without changing the
  inference contract.

## Alternatives considered

- Context-only P(recovery) without action: rejected — cannot compare interventions.
- Letting the classifier pick the argmax action: rejected — that is ERV + policy,
  not probability estimation.
- Uncalibrated tree scores optimized for accuracy: rejected — unsafe for money.
- Crashing the API when the artifact is absent: rejected — demo and worker must
  still run.
- Evaluating on the training set: rejected — leakage and overfit theater.
