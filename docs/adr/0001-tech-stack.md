# ADR 0001: Week01 Technical Stack

## Status

Accepted

## Context

The project needs a reproducible research backend, read-only Polymarket data probes, and a future dashboard. The USA VPS is limited in storage and CPU and must stay outside the private-key and order-execution boundary.

## Decision

- Backend: Python 3.11+, FastAPI, Pydantic, `httpx`, structured JSON logging.
- API probes: Python module under `backend/scripts`, with sanitized JSON samples under `docs/samples`.
- Storage target: PostgreSQL plus Redis locally via Docker Compose; schemas are deferred to Week02.
- Frontend target: Next.js + TypeScript placeholder in Week01.
- VPS role: read-only API probe and later collection node. It should not run Docker for now and must not store secrets or trading credentials.

## Consequences

- Local development can use Docker Compose for Postgres/Redis/backend.
- VPS validation can run direct Python/curl probes without Docker.
- All ingestion runs carry a `run_id` to preserve provenance.
- Real order execution and signing remain out of scope for Week01.

