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
- CLOB token mapping verification through the public `markets-by-token/{token_id}` endpoint.

The worker does not use private keys, cookies, signatures, trading credentials, or order endpoints.

Pagination and token verification are based on the official public docs:

- [Gamma keyset pagination](https://docs.polymarket.com/api-reference/markets/list-markets-keyset-pagination)
  uses response `next_cursor` as the next request's `after_cursor`.
- [CLOB `markets-by-token/{token_id}`](https://docs.polymarket.com/api-reference/markets/get-market-by-token)
  resolves a token ID back to its parent market.

## Commands

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate
python -m backend.scripts.db_migrate
python -m backend.scripts.ingest_market_data --max-markets 5 --page-limit 5 --holders-market-limit 2 --holders-limit 3
python -m backend.scripts.ingest_market_data --max-markets 500 --page-limit 100 --holders-market-limit 25 --holders-limit 50 --token-verification-limit 100
```

## Local Verification

Schema migration on local PostgreSQL:

```text
Applied schema migration: 2026_07_09_week02_schema_v1
```

Two repeated small ingestion runs completed successfully. After the second small run:

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

A full Week02 scale run also completed successfully:

```text
run_id: market_data_20260709T035232Z_a4b44e8a
markets: 500
tokens: 1000
events: 228
market_pages: 5
token_verifications: 100
token_mapping_failures: 0
holders: 2500
liquidity_snapshots: 526
raw_responses: 157
warning: gamma_market_category_missing_retained_for_ingestion
```

A follow-up 500-market run with holders and token verification disabled confirmed main-table
idempotency:

```text
events: 228
markets: 500
market_tokens: 1000
mapping_status.verified: 100
mapping_status.mapped: 900
latest_error: None
```

## Tests

```text
pytest -q: 13 passed, 1 warning
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
- Gamma active market responses observed on 2026-07-09 did not include category or tag fields for
  current markets or embedded events. The worker keeps uncategorized markets instead of dropping them
  and records `gamma_market_category_missing_retained_for_ingestion`.
- Category filtering is implemented for records that do include a category. A later enrichment pass
  should fill missing categories from event/tag detail endpoints before category-specific analytics.
