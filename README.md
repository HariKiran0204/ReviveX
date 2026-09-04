# ReviveX — RecoverAI

Autonomous Revenue Recovery Orchestrator for Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery.

ReviveX detects failed-payment revenue at risk, scores each recovery action with a calibrated ML model (`P(recovery | case, action)`), ranks interventions by Expected Recovery Value, enforces policy guardrails, executes side-effects through idempotent tools, verifies recovery only when a real capture arrives, and reports a measured baseline-vs-ReviveX evaluation across deterministic paired counterfactual simulations.

It does not call Razorpay production APIs, fabricate recovered revenue, or treat every capture as a recovery.

## Overview

ReviveX is a complete, end-to-end autonomous revenue recovery system. The core loop is:

1. **Detect** — a failed payment event creates a `RecoveryCase`.
2. **Score** — the `recovery-v1` ML model estimates `P(recovery | case, action)` for each candidate action.
3. **Rank** — the ERV optimizer picks the highest expected-value legal intervention.
4. **Enforce** — PolicyEngine allows, requires human approval, or blocks the action.
5. **Execute** — bounded tools (retry, payment link, discount, reminder) run idempotently.
6. **Verify** — `RecoveryVerificationService` credits revenue only when a matching capture arrives within the recovery window.
7. **Measure** — a paired counterfactual batch evaluator compares ReviveX against a passive DO_NOTHING baseline across multiple seeds.

The operator UI (Evaluation Center) surfaces live batch evaluation results from the trained model.

## Problem

Merchants lose revenue to failed payments, abandoned checkouts, and failed subscriptions. Passive detection is not enough. ReviveX closes the full loop: detect → score → rank → enforce → execute → verify → measure.

## Architecture

See [docs/architecture/overview.md](docs/architecture/overview.md).

Short version: Next.js talks to FastAPI; FastAPI checks PostgreSQL and Redis; an RQ worker heartbeats on Redis and runs ingestion, case processing, and verification jobs.

## Repository structure

```
apps/api          FastAPI
apps/web          Next.js shell
apps/worker       RQ worker
packages/domain   Domain events, ingestion, processing
packages/db       SQLAlchemy models, Alembic, repositories
packages/providers  PaymentProvider + local simulator
packages/eval      Recovery-probability training and inference
data/             Synthetic ML datasets and model artifacts (generated)
docs/             Architecture and ADRs
infra/            Docker Compose and Dockerfiles
scripts/          Developer helpers
tests/            Python tests
```

## Technology stack

- Python 3.12, FastAPI, Pydantic v2, uv, Ruff, mypy, pytest
- Next.js, React, TypeScript, Tailwind CSS, pnpm, Vitest
- PostgreSQL 16, Redis 7, RQ
- Docker Compose

## Prerequisites

- Python 3.12
- Node.js 22
- [uv](https://docs.astral.sh/uv/)
- pnpm 9 (`corepack enable` on Unix, or `npx pnpm@9.15.0` on Windows if corepack cannot write to Node’s install directory)
- Docker Desktop / Docker Engine (for Compose)

## Quick start

### 1. Train the recovery-v1 model artifact (required for Evaluation Center)

The Evaluation Center runs live batch evaluation using the trained `recovery-v1` model artifact. Model artifacts are not committed to the repository. **Run this once before starting the services:**

```bash
uv sync --group dev
uv run python -m recoverai_eval.train --seed 42 --n-cases 10000
```

This generates the `recovery-v1` artifact under `data/ml/`. If the artifact is missing, the Evaluation Center endpoint will raise an error. Training takes under a minute on a modern machine.

### 2. Start the services

```bash
cp .env.example .env
uv sync --group dev
corepack enable
pnpm install
# Windows fallback if corepack cannot enable pnpm globally:
# npx pnpm@9.15.0 install
docker compose -f infra/docker-compose.yml up --build
```

Then open:

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Ready: http://localhost:8000/ready
- Web: http://localhost:3000
- Evaluation Center: http://localhost:3000/evaluation

> **Note:** The Evaluation Center runs live paired counterfactual batch evaluation across multiple deterministic seeds on every page load. The initial load may take approximately 10–30 seconds depending on machine speed. This is evaluation computation, not a broken page.

Without Docker, run the API locally (Postgres/Redis optional in development; `/ready` will mark them `skipped` if unset):

```bash
uv run uvicorn recoverai_api.main:app --reload --app-dir apps/api --port 8000
pnpm --filter recoverai-web dev
```

The worker requires Redis (and Postgres for event processing):

```bash
uv run python -m recoverai_worker
```

Set `PYTHONPATH` to `apps/api;apps/worker;packages/domain;packages/db;packages/providers;packages/eval` on Windows, or `apps/api:apps/worker:packages/domain:packages/db:packages/providers:packages/eval` on Unix, if you are not using `uv run` from the Makefile layout. `uv run pytest` already sets `pythonpath` via `pyproject.toml`.

## Environment variables

See [.env.example](.env.example). Do not commit `.env` or real API keys.

`LLM_*` defaults to the stub provider. Phase 8 agents fall back to deterministic rules when the LLM is unavailable. `RAZORPAY_*` remains unused. `PAYMENT_PROVIDER=simulator` and `SIMULATION_SEED=42` control the local simulator. `RECOVERY_WINDOW_HOURS` (default 72) bounds which captures can count as recovery.

## Development commands

GNU Make is optional (`make` is not required on Windows):

| Make target | Equivalent |
| --- | --- |
| `make setup` | `uv sync --group dev` and `pnpm install` |
| `make dev` | `docker compose -f infra/docker-compose.yml up --build` |
| `make test` | `uv run pytest` and `pnpm --filter recoverai-web test` |
| `make lint` | Ruff, mypy, Next lint, `tsc` |
| `make format` | `uv run ruff check --fix` and `ruff format` |
| `make health` | `uv run python scripts/health.py` |
| `make seed` | `uv run alembic upgrade head` then `uv run python scripts/seed.py` |
| `make migrate` | `uv run alembic upgrade head` |
| `make demo` | Prints Phase 4 scenario and recovery endpoints |

## Health checks

- `GET /health` — process liveness (`{"status":"ok","service":"recoverai-api"}`)
- `GET /ready` — application plus configured Postgres and Redis. Returns HTTP 503 with `status: not_ready` when a configured dependency is down. Unconfigured dependencies in development are `skipped`.

The web header polls these endpoints. It does not assume the API is healthy.

## Testing

```bash
uv run pytest
pnpm --filter recoverai-web test
```

CI runs the same checks in [.github/workflows/ci.yml](.github/workflows/ci.yml) without secrets.

## Current phase

**Phase 9 — Operator UI.** The Next.js app is a view/control surface over FastAPI. Command Center, cases, case detail, approvals, policy, audit, evaluation, system health, and demo controls read and command the existing backend. The browser never writes `amount_recovered`. See [docs/architecture/operator-ui.md](docs/architecture/operator-ui.md).

**Phase 8 — Multi-agent orchestration.** Bounded triage, diagnosis, strategy, explanation, and analyst agents with versioned prompts and deterministic fallback. They consume Phase 6 probabilities and Phase 7 `OptimizationResult`. Policy and `ToolExecutionService` remain the execution boundary. See [docs/architecture/agent-system.md](docs/architecture/agent-system.md).

```bash
curl -s -X POST http://localhost:8000/v1/recovery-cases/{id}/agent-run \
  -H "content-type: application/json" \
  -d "{\"execute\":false}"
```

**Phase 7 — Expected Recovery Value optimizer.** Deterministic ranking of legal interventions from Phase 6 probabilities, configurable prototype costs, and PolicyEngine as the allow/approve/block authority. The optimizer does not execute tools or credit recovered revenue. See [docs/architecture/erv-optimizer.md](docs/architecture/erv-optimizer.md).

```bash
curl -s -X POST http://localhost:8000/v1/recovery-cases/{id}/optimize
```

**Phase 6 — Recovery probability model.** Action-conditioned `P(recovery | case, action)`, calibrated sklearn pipelines, versioned artifacts, and a deterministic `MODEL_FALLBACK` scorer. The model does not select the intervention, execute tools, or credit recovered revenue. See [docs/architecture/recovery-model.md](docs/architecture/recovery-model.md).

```bash
uv run python -m recoverai_eval.train --seed 42 --n-cases 10000
uv run python -m recoverai_eval.evaluate --model-version recovery-v1
# or: uv run python scripts/train_recovery_model.py --seed 42 --n-cases 10000
```

**Phase 5 — Policy engine and safe tool execution.** Deterministic policy, registered tools, idempotent provider side effects, and human approval. See [docs/architecture/policy-and-tools.md](docs/architecture/policy-and-tools.md).

Example (after API + Postgres are up; simulation creates a demo merchant automatically):

```bash
curl -s -X POST http://localhost:8000/v1/simulation/scenarios \
  -H "content-type: application/json" \
  -d "{\"scenario\":\"G\",\"seed\":42,\"amount\":\"4000.00\"}"
# Run the worker so process_provider_event, process_recovery_case, and verify_recovery_case execute.
```

Development triggers (run the real backend workflow; they do not assign `RECOVERED` directly):

```bash
curl -s -X POST http://localhost:8000/v1/recovery-cases/{id}/process
curl -s -X POST http://localhost:8000/v1/recovery-cases/{id}/actions/evaluate \
  -H "content-type: application/json" \
  -d "{\"action\":\"RETRY_NOW\"}"
curl -s -X POST http://localhost:8000/v1/recovery-cases/{id}/actions/execute \
  -H "content-type: application/json" \
  -d "{\"tool_name\":\"retry_payment\",\"idempotency_key\":\"demo-retry-1\",\"input\":{}}"
curl -s -X POST http://localhost:8000/v1/recovery-cases/{id}/verify
```

### Database commands

```bash
cp .env.example .env
# Ensure DATABASE_URL is set (postgresql+psycopg://recoverai:recoverai@localhost:5432/recoverai)
uv run alembic upgrade head
uv run python scripts/seed.py
uv run alembic downgrade base   # rollback Phase 2 schema
```

Database architecture: [docs/architecture/database.md](docs/architecture/database.md)

## Roadmap

2. ~~Domain schema and Alembic~~ (Phase 2 complete)  
3. ~~Simulator / provider interface~~ (Phase 3 complete)  
4. ~~Recovery state machine~~ (Phase 4 complete)  
5. ~~Policy and tools~~ (Phase 5 complete)  
6. ~~ML probability model (recovery-v1)~~ (Phase 6 complete)  
7. ~~ERV optimizer~~ (Phase 7 complete)  
8. ~~Specialized agents~~ (Phase 8 complete)  
9. ~~Full operator UI bound to cases~~ (Phase 9 complete)  
10. ~~Paired counterfactual batch evaluator and Evaluation Center~~ (complete)  
11. Razorpay test-mode adapter  
12. Auth, RBAC, observability  

## Important design principles

- Execute and verify; do not fabricate recovered revenue.
- LLM reasons; tools execute; policy is authoritative.
- Local simulator is the default provider. Razorpay test mode is an adapter, not a hard dependency.

## Simulation vs real provider integration

Phase 3 ships a **local simulator** behind `PaymentProvider`. Demo events use a deterministic `recoverai-demo` merchant created on first simulation call (`seed.py` is optional). Razorpay API calls are still not implemented. The same ingestion path will accept a Razorpay adapter later.
