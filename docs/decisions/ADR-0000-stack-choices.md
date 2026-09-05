# ADR-0000: Stack choices

**Status:** Accepted  
**Date:** 2026-09-03  
**Phase:** 1 — Foundation

## Context

RecoverAI needs a production-minded prototype that can later run recovery workflows, workers, and an operator UI. The repository was empty. The stack must be simple enough to demo locally without a distributed platform.

## Decision

| Concern | Choice |
| --- | --- |
| Operator UI | Next.js (App Router), React, TypeScript, Tailwind CSS |
| HTTP API | FastAPI, Pydantic v2, Uvicorn, Python 3.12 |
| Database | PostgreSQL 16 |
| Queue / cache | Redis 7 + RQ |
| Python deps | uv |
| JS deps | pnpm workspaces |
| Local runtime | Docker Compose |

RQ is used instead of Celery because the Phase 1 workload is a single queue and a heartbeat. Kafka (or any log broker) is **not** introduced: there is no high-throughput pub/sub requirement yet, and extra brokers would obscure the recovery loop rather than clarify it.

## Consequences

- API and worker share one Python environment and `PYTHONPATH`.
- Compose starts Postgres, Redis, API, worker, and web with health conditions.
- Evaluation, agents, and Razorpay adapters can be added without replacing this backbone.

## Alternatives considered

- Celery: heavier broker conventions than needed for a single inspectable queue.
- Poetry: uv is faster and already used on the development machine.
- npm/yarn: pnpm fits a small workspace (`apps/web` only).
