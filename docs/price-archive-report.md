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
  - `market_followability_snapshots`
  - `trade_clv_metrics`
- Added `backend.app.collectors.price_data` for:
  - price history normalization
  - order book top-of-book and finite depth normalization
  - market WebSocket event normalization with `received_at`
  - direction-adjusted CLV helpers
  - bulk CLV materialization for stored trades
  - conservative book-depth slippage estimation
  - followability flags and liquidity scoring
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

# CLV materialization
python -m backend.scripts.archive_price_data \
  --skip-history \
  --skip-orderbook \
  --calculate-clv \
  --clv-limit 1000

# 24-hour watchlist shape: order book every 30s, WebSocket for 24h
python -m backend.scripts.archive_price_data \
  --tokens <comma_separated_watchlist_tokens> \
  --skip-history \
  --orderbook-cycles 2880 \
  --orderbook-interval-seconds 30 \
  --websocket \
  --websocket-seconds 86400 \
  --websocket-event-limit 1000000
```

## Data Policy

- `price_points.price_at` is UTC.
- `orderbook_snapshots.snapshot_at` is local system receipt time for the HTTP `book` response.
- `market_stream_events.received_at` is always recorded and is the primary latency reference.
- `market_stream_events.event_at` is parsed from the payload when present, but WebSocket events may
  arrive delayed or out of order.
- Historical prices are not treated as historical order book depth and must not be used to claim
  precise slippage simulation.
- CLV materialization prefers archived midpoint at or after the requested horizon and falls back to
  `price_points` when no midpoint is available.

## Validation

Unit tests cover:

- CLOB price history normalization.
- top-of-book, midpoint, spread, and finite depth normalization.
- WebSocket event timestamp preservation.
- CLV sign adjustment by trade direction.
- conservative depth-based slippage estimation.
- followability flags for wide spread, insufficient depth, and missing top-of-book prices.

Expected verification commands:

```bash
pytest -q
ruff check .
```

Local Week05 smoke:

```text
python -m backend.scripts.db_migrate
Applied schema migration: 2026_07_09_week05_price_archive_schema_v2

python -m backend.scripts.archive_price_data --tokens <sample_token> --token-limit 1 --depth-limit 3
price_points: 1441 attempted / 1440 stored after idempotent upsert
orderbook_snapshots: 1
orderbook_depth_rows: 6
failed_tokens: 0

python -m backend.scripts.archive_price_data --tokens <sample_token> --skip-history --skip-orderbook --websocket --websocket-seconds 2 --websocket-event-limit 2
market_stream_events: 1
websocket_reconnects: 0

python -m backend.scripts.archive_price_data --token-limit 100 --skip-orderbook
tokens: 100
raw_responses: 100
price_points: 144101 attempted
failed_tokens: 0

python -m backend.scripts.archive_price_data --token-limit 5 --skip-history --orderbook-cycles 3 --orderbook-interval-seconds 2 --depth-limit 5 --websocket --websocket-seconds 10 --websocket-event-limit 10
orderbook_snapshots: 15
orderbook_depth_rows: 150
followability_snapshots: 15
market_stream_events: 10
websocket_reconnects: 0

python -m backend.scripts.archive_price_data --token-limit 5 --skip-history --skip-orderbook --calculate-clv --clv-limit 200
trade_clv_metrics: 200
rows_with_any_clv: 19
```

## Known Limits

- The CLI supports the 24-hour watchlist run shape, but this code pass validated it with a bounded
  10-second WebSocket run and 3 order book cycles instead of waiting for a full day.
- PnL still stores placeholder `estimated_slippage=0`; Week05 data is now available for a later
  PnL enrichment pass.
