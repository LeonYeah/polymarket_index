# Price and Order Book Archive Report

Date: 2026-07-09

## Scope

Week05 adds read-only CLOB market microstructure archiving. It consumes public
`prices-history`, `book`, and market WebSocket data only. It does not call order placement
endpoints and does not require private keys, cookies, signatures, or trading credentials.

## Implemented

- Added schema tables:
  - `price_points`
  - `orderbook_snapshots`
  - `orderbook_top`
  - `orderbook_depth_snapshots`
  - `market_stream_events`
- Added `backend.app.collectors.price_data` for:
  - price history normalization
  - order book top-of-book and finite depth normalization
  - market WebSocket event normalization with `received_at`
  - direction-adjusted CLV helpers
  - conservative book-depth slippage estimation
- Added `backend.app.db.price_repository`.
- Added CLI:

```bash
python -m backend.scripts.archive_price_data --token-limit 100
```

Useful bounded runs:

```bash
# One-token HTTP smoke: prices-history + book
python -m backend.scripts.archive_price_data \
  --tokens <clob_token_id> \
  --token-limit 1 \
  --depth-limit 3

# Short WebSocket smoke
python -m backend.scripts.archive_price_data \
  --tokens <clob_token_id> \
  --skip-history \
  --skip-orderbook \
  --websocket \
  --websocket-seconds 2 \
  --websocket-event-limit 2
```

## Data Policy

- `price_points.price_at` is UTC.
- `orderbook_snapshots.snapshot_at` is local system receipt time for the HTTP `book` response.
- `market_stream_events.received_at` is always recorded and is the primary latency reference.
- `market_stream_events.event_at` is parsed from the payload when present, but WebSocket events may
  arrive delayed or out of order.
- Historical prices are not treated as historical order book depth and must not be used to claim
  precise slippage simulation.

## Validation

Unit tests cover:

- CLOB price history normalization.
- top-of-book, midpoint, spread, and finite depth normalization.
- WebSocket event timestamp preservation.
- CLV sign adjustment by trade direction.
- conservative depth-based slippage estimation.

Expected verification commands:

```bash
pytest -q
ruff check .
```

Local Week05 smoke:

```text
python -m backend.scripts.db_migrate
Applied schema migration: 2026_07_09_week05_price_archive_schema_v1

python -m backend.scripts.archive_price_data --tokens <sample_token> --token-limit 1 --depth-limit 3
price_points: 1441 attempted / 1440 stored after idempotent upsert
orderbook_snapshots: 1
orderbook_depth_rows: 6
failed_tokens: 0

python -m backend.scripts.archive_price_data --tokens <sample_token> --skip-history --skip-orderbook --websocket --websocket-seconds 2 --websocket-event-limit 2
market_stream_events: 1
websocket_reconnects: 0
```

## Known Limits

- The CLI supports short bounded WebSocket archiving, but a 24-hour supervised run has not been
  completed in this code pass.
- CLV helpers are implemented as pure functions; bulk CLV materialization for stored Week03/Week04
  trades still needs a dedicated job.
- PnL still stores placeholder `estimated_slippage=0`; Week05 data is now available for a later
  PnL enrichment pass.
