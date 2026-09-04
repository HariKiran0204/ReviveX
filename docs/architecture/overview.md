# RecoverAI architecture

Autonomous Revenue Recovery Orchestrator for Razorpay AI Buildathon 2026 — Track 03.

This document describes the **target** system and what is implemented through Phase 9.

## Implemented now (Phase 1–9)

- Next.js operator application bound to FastAPI (`apps/web`) — see [operator-ui.md](architecture/operator-ui.md)
- FastAPI application with `/health`, `/ready`, recovery workflow, and operator read APIs (`apps/api`)
- RQ worker heartbeat plus `process_provider_event`, `process_recovery_case`, `verify_recovery_case` (`apps/worker`)
- Redis and PostgreSQL via Docker Compose (`infra/docker-compose.yml`)
- Typed configuration, structured logs, request IDs
- **Phase 2:** PostgreSQL domain schema, Alembic migrations, repositories, deterministic seed data
- **Phase 3:** provider abstraction, local payment simulator, webhook/event ingestion, normalized domain events, recovery-case creation on payment failure
- **Phase 4:** legal recovery state machine, row-lock concurrency, deterministic case processor, recovery verification and accounting
- **Phase 5:** deterministic policy engine, tool registry, ToolExecutionService, idempotency, human approval, simulator-backed side effects
- **Phase 6:** action-conditioned recovery probability model, calibration, versioned artifacts, `model_versions` / `model_predictions`
- **Phase 7:** deterministic Expected Recovery Value optimizer, configurable costs, policy-filtered ranking, append-only `recovery_decisions`
- **Phase 8:** bounded specialized agents, versioned prompts, deterministic LLM fallback, orchestrated triage→diagnosis→strategy→ERV→policy
- **Phase 9:** operator UI over real APIs (command center, cases, case detail, approvals, policy, audit, evaluation, health, demo)

See [docs/architecture/database.md](architecture/database.md), [docs/architecture/provider-and-events.md](architecture/provider-and-events.md), [docs/architecture/recovery-state-machine.md](architecture/recovery-state-machine.md), [docs/architecture/policy-and-tools.md](architecture/policy-and-tools.md), [docs/architecture/recovery-model.md](architecture/recovery-model.md), [docs/architecture/erv-optimizer.md](architecture/erv-optimizer.md), [docs/architecture/agent-system.md](architecture/agent-system.md), and [docs/architecture/operator-ui.md](architecture/operator-ui.md).

No Razorpay calls exist yet. The default LLM provider is `stub`; agents fall back to deterministic rules.

## Planned later

```
Frontend  →  FastAPI  →  RQ workers
                │            │
                ▼            ▼
           PostgreSQL      Redis
                ▲
     webhooks / simulator events
```

| Layer | Responsibility |
| --- | --- |
| Frontend | Command Center, cases, case detail, approvals, policy, audit, evaluation — bound to real API state |
| FastAPI | HTTP API, webhook ingest, orchestration entry |
| RQ + Redis | Async recovery jobs, heartbeat, scheduled retries |
| PostgreSQL | Source of truth for cases, actions, audit |
| Agent layer | Structured triage, diagnosis, strategy, explanation, analyst (Phase 8) |
| ML | `P(recovery \| context, action)` (Phase 6; does not select the action) |
| ERV optimizer | Deterministic expected recovery value ranking (Phase 7) |
| Policy engine | Fail-closed allow / approve / block (Phase 5) |
| Tool layer | Idempotent, audited side effects; LLM cannot call providers directly (Phase 5) |
| Provider adapters | Local simulator (default) and Razorpay **test mode** |
| Events | Webhooks with signature, dedupe, out-of-order handling |
| Verification | Credits recovered revenue only after a matching captured payment |
| Evaluation | Batch run vs baseline; measured uplift; honest exceptions |

## Phase 3 loop (implemented)

```
SIMULATED PAYMENT EVENT
→ POST /v1/webhooks/simulator (or /v1/simulation/*)
→ persist webhook_events (provider=SIMULATOR)
→ deduplicate (provider, event_id)
→ enqueue process_provider_event
→ normalize to domain events
→ update payments / create DETECTED recovery case on failure
→ audit_events
```

Captured payments update payment state and write audit records. They enqueue `verify_recovery_case`; recovered revenue is credited only after verification (Phase 4).

## Design constraints

- The LLM never executes financial actions.
- Money uses decimal/NUMERIC types (Phase 2+).
- Simulator remains available without Razorpay credentials.
- Duplicate webhooks must not duplicate side effects.
- Provider SDK types must not leak into domain processing.
