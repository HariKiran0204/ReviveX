# ADR-0001: Database and money representation

**Status:** Accepted  
**Date:** 2026-09-03  
**Phase:** 2 — Domain schema

## Context

RecoverAI must persist multi-tenant recovery state with auditable financial records. Phase 2 introduces PostgreSQL schema only — no recovery orchestration yet.

## Decisions

### PostgreSQL + SQLAlchemy 2.x + Alembic

- Typed `Mapped[]` models in focused modules under `packages/db/recoverai_db/models/`
- UUID internal primary keys; provider IDs stored separately
- Alembic revision `20260903_0001` generates the full Phase 2 schema

### Multi-tenancy

- Every merchant-owned row includes `merchant_id`
- Repositories require explicit `merchant_id` parameters
- `merchant_memberships` enforces unique `(merchant_id, user_id)`

### Money

- `NUMERIC(18,2)` in PostgreSQL
- Python `Decimal` in application code
- Check constraints for non-negative amounts where business rules require it
- Optional `BIGINT` minor-unit columns for provider compatibility

### Open recovery case constraint

Partial unique indexes on `recovery_cases` keyed by payment/cart/subscription while `closed_at IS NULL`. This prevents duplicate active recovery work without blocking historical closed cases.

### Idempotency and webhooks

- `idempotency_keys`: unique `(merchant_id, key)`
- `recovery_actions`: unique `(merchant_id, idempotency_key)`
- `webhook_events`: unique `(provider, event_id)`

### What Phase 2 explicitly does not do

- State machine transitions
- Policy enforcement execution
- Webhook processing
- Agent/ML persistence beyond structured storage tables

## Consequences

- `/ready` can report real database connectivity when `DATABASE_URL` is configured
- Phase 3 provider adapters can persist payments/webhooks without schema rework
- Evaluation datasets (10k+) remain a later phase — Phase 2 seed is small and deterministic

## Alternatives considered

- Float columns: rejected — unacceptable for payment systems
- Single `models.py`: rejected — poor maintainability at this domain size
- Application-only tenant filtering: rejected — repositories enforce merchant scope now
