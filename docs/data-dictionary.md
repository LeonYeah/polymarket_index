# Data Dictionary Draft

All timestamps must be normalized to UTC. Decimal values should be stored as decimal strings or fixed-precision numeric columns, not binary floats.

## Market

| Field | Type | Source | Notes |
|---|---|---|---|
| `condition_id` | string | Gamma/CLOB | Primary market condition identifier when present. |
| `market_slug` | string | Gamma | Human-readable stable URL slug. |
| `question` | string | Gamma | Market question text. |
| `event_id` | string | Gamma | Parent event identifier when present. |
| `active` | boolean | Gamma | Whether market is active. |
| `closed` | boolean | Gamma | Whether market is closed. |
| `end_time_utc` | timestamp | Gamma | Normalize from API string/time field to UTC. |
| `clob_token_ids` | string[] | Gamma | Outcome token IDs; preserve as strings because IDs exceed integer-safe ranges. |

## Wallet

| Field | Type | Source | Notes |
|---|---|---|---|
| `wallet_address` | string | Data API | Lowercase normalized address for joins; keep original if displayed. |
| `first_seen_utc` | timestamp | Derived | First observed trade/position. |
| `last_seen_utc` | timestamp | Derived | Last observed trade/position. |
| `source_run_id` | string | Internal | Probe or ingestion run that discovered the wallet. |
| `seed_source` | enum | Derived | Candidate source: leaderboard, holder, active_trader, manual_watchlist. |
| `active_days_180d` | integer | Derived | Count of trade-active UTC dates in the last 180 days. |
| `markets_count` | integer | Derived | Distinct markets seen in stored trades. |
| `notional_30d/90d/180d` | decimal | Derived | Rolling trade notional windows from stored trades. |

## Trade

| Field | Type | Source | Notes |
|---|---|---|---|
| `trade_id` | string | Data API | Prefer API id/transaction hash plus log index when available. |
| `wallet_address` | string | Data API | Usually taker/proxy wallet; maker fields must be handled separately. |
| `market` | string | Data API | Market/condition reference from response. |
| `asset_id` | string | Data/CLOB | Outcome token ID; store as string. |
| `side` | enum | Data API | Buy/sell or equivalent. |
| `price` | decimal | Data API | Execution price, not UI display price. |
| `size` | decimal | Data API | Outcome share amount. |
| `notional` | decimal | Derived | `price * size`, with explicit quote currency. |
| `timestamp_utc` | timestamp | Data API | Confirm seconds vs milliseconds during probe and normalize. |
| `taker_only_mode` | boolean | Probe metadata | `/trades` must explicitly set `takerOnly`; default can hide maker-style activity. |
| `trade_uid` | string | Derived | Stable hash when API has no durable trade id. |

## Position

| Field | Type | Source | Notes |
|---|---|---|---|
| `wallet_address` | string | Data API | Position owner. |
| `condition_id` | string | Data/Gamma | Market condition identifier when present. |
| `asset_id` | string | Data/CLOB | Outcome token ID. |
| `outcome` | string | Data API | Yes/No or multi-outcome label. |
| `size` | decimal | Data API | Current shares. |
| `avg_price` | decimal | Data/Derived | Average entry price if available, otherwise derive from fills. |
| `current_value` | decimal | Data API | Marked value; do not treat as realized PnL. |
| `realized_pnl` | decimal | Closed positions | Only resolved/closed PnL should feed realized performance. |
| `cash_pnl` | decimal | Current positions | Unrealized or marked PnL, kept separate from realized PnL. |
| `position_uid` | string | Derived | Stable hash over wallet, market, token, and closed timestamp for closed positions. |

## Wallet Backfill Checkpoint

| Field | Type | Source | Notes |
|---|---|---|---|
| `wallet_address` | string | Internal | Wallet being backfilled. |
| `endpoint` | string | Internal | `/trades`, `/positions`, or `/closed-positions`. |
| `taker_only` | boolean | Internal | Explicit `/trades` mode; false is stored for non-trade endpoints. |
| `next_offset` | integer | Internal | Offset to resume paged backfills. |
| `status` | enum | Internal | running, exhausted, succeeded, or failed. |

## Price

| Field | Type | Source | Notes |
|---|---|---|---|
| `asset_id` | string | CLOB | Outcome token ID. |
| `timestamp_utc` | timestamp | CLOB | Normalize all history points to UTC. |
| `price` | decimal | CLOB | Historical price/midpoint depending on endpoint parameter. |
| `bid` | decimal | CLOB | Best bid for live snapshots. |
| `ask` | decimal | CLOB | Best ask for live snapshots. |
| `midpoint` | decimal | Derived/CLOB | `(bid + ask) / 2` when both sides exist. |

## Order Book

| Field | Type | Source | Notes |
|---|---|---|---|
| `asset_id` | string | CLOB | Outcome token ID. |
| `snapshot_utc` | timestamp | Internal | Time the book response was observed. |
| `bids` | array | CLOB | Price/size levels as decimal strings. |
| `asks` | array | CLOB | Price/size levels as decimal strings. |
| `spread` | decimal | CLOB/Derived | Best ask minus best bid. |
| `depth_notional` | decimal | Derived | Future followability metric at fixed slippage bands. |
