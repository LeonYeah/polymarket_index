# Week02 Market Data Ingestion Report

Collected at: 2026-07-09

## Scope

Week02 adds PostgreSQL schema v1 and a read-only market data ingestion worker for:

- Gamma markets and embedded events.
- Gamma event page samples.
- Market token mappings from `clobTokenIds` and `outcomes`.
- Market capacity snapshots from Gamma market fields, Data `oi`, and Data `live-volume`.
- Top holders from Data `holders`.
- Raw API response capture with request params, status code, duration, row count, hash, and JSON body.

The worker does not use private keys, cookies, signatures, trading credentials, or order endpoints.

## Commands

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate
python -m backend.scripts.db_migrate
python -m backend.scripts.ingest_market_data --max-markets 5 --page-limit 5 --holders-market-limit 2 --holders-limit 3
```

## Local Verification

Schema migration on local PostgreSQL:

```text
Applied schema migration: 2026_07_09_week02_schema_v1
```

Two repeated small ingestion runs completed successfully. After the second run:

```text
ingestion_runs: 2
events: 6
markets: 5
market_tokens: 10
market_liquidity_snapshots: 16
market_holders: 24
raw_api_responses: 14
failed_token_mappings: 0
```

This verifies that market, event, and token writes are idempotent while run-scoped snapshots,
holders, and raw responses remain auditable per ingestion batch.

## Tests

```text
pytest -q: 10 passed, 1 warning
ruff check .: All checks passed
```

The warning is from Starlette/FastAPI test client compatibility and does not affect the current
implementation.

## Notes

- `clobTokenIds` and `outcomes` are parsed as JSON arrays when Gamma returns JSON strings.
- CLOB token IDs are stored as text.
- Decimal-like values are parsed with `Decimal`.
- Time values are normalized to UTC and millisecond timestamps are handled.
- `data/live-volume` can return condition IDs outside the current market batch; liquidity snapshots
  intentionally preserve external market IDs without enforcing a foreign key to `markets`.
- The Gamma keyset cursor behavior should be rechecked before a large historical backfill. The worker
  records raw responses and stops if cursor results repeat.
