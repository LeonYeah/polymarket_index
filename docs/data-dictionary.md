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

## Wallet Market Result

| Field | Type | Source | Notes |
|---|---|---|---|
| `result_uid` | string | Derived | Stable hash over wallet, condition, token, and outcome. |
| `wallet_address` | string | Derived | Lowercase normalized wallet. |
| `condition_id` | string | Data/Gamma | Market condition id; missing ids are marked `mapping_failed`. |
| `token_id` | string | Data/CLOB | Outcome token id. |
| `market_status` | enum | Derived | open, closed, archived, or unknown from `market_resolution_status`. |
| `result_status` | enum | Derived | open, closed, settled, archived, disputed, cancelled, mapping_failed, unknown. |
| `realized_pnl` | decimal | Closed positions | Sum of `wallet_positions_closed.realized_pnl`; current marked value is excluded. |
| `unrealized_pnl` | decimal | Current positions | Sum of `wallet_positions_current.cash_pnl`; does not feed realized score. |
| `current_value` | decimal | Current positions | Marked value retained for exposure analysis only. |
| `capital_deployed` | decimal | Derived | V1 uses max(total buy notional minus total sell notional, 0). |
| `net_roi` | decimal | Derived | `(realized + unrealized - estimated fees - estimated slippage) / capital_deployed`. |
| `estimated_fees` | decimal | Placeholder | V1 stores zero with `fees_estimated=true`; Week05 can refine from order book/fee model. |
| `estimated_slippage` | decimal | Placeholder | V1 stores zero with `slippage_estimated=true`; Week05 can refine from order book. |
| `outcome_correct` | boolean | Derived | Only set when a closed market has enough source price evidence. |

## Wallet Daily Equity

| Field | Type | Source | Notes |
|---|---|---|---|
| `wallet_address` | string | Derived | Wallet being summarized. |
| `equity_date` | date | Derived | UTC trade/close date. |
| `realized_pnl_cumulative` | decimal | Derived | Cumulative closed-position realized PnL through the date. |
| `unrealized_pnl` | decimal | Derived | Current unrealized PnL on calculation date only in v1. |
| `net_pnl` | decimal | Derived | Realized cumulative plus v1 unrealized point-in-time value. |
| `drawdown` | decimal | Derived | Peak-to-current decline in the v1 daily curve. |
| `max_drawdown` | decimal | Derived | Maximum observed drawdown through the date. |

## PnL Reconciliation Check

| Field | Type | Source | Notes |
|---|---|---|---|
| `check_type` | enum | Internal | V1 starts with `closed_position_realized_pnl`. |
| `status` | enum | Derived | matched or different. |
| `diff_category` | enum | Derived | matched, field_missing, time_window_different, fee_basis_different, mapping_failed, unknown. |
| `engine_realized_pnl` | decimal | Derived | PnL engine output for the wallet-market-token. |
| `source_realized_pnl` | decimal | Data API | Closed position realized PnL used for comparison. |
| `difference` | decimal | Derived | Engine minus source value. |

## Price Archive

| Field | Type | Source | Notes |
|---|---|---|---|
| `price_points.asset_id` | string | CLOB | Outcome token ID. |
| `price_points.condition_id` | string | CLOB | Market/condition ID when available in payload. |
| `price_points.price_at` | timestamp | CLOB | Historical point timestamp normalized to UTC. |
| `price_points.price` | decimal | CLOB | Historical price from `prices-history`. Not historical depth. |
| `price_points.source_endpoint` | string | Internal | Currently `clob.prices-history`. |
| `price_points.interval` | string | CLOB request | Requested interval, for example `1d`. |
| `price_points.fidelity` | integer | CLOB request | Requested fidelity when supplied. |

## Order Book

| Field | Type | Source | Notes |
|---|---|---|---|
| `orderbook_snapshots.snapshot_uid` | string | Derived | Stable snapshot ID for top and depth rows. |
| `orderbook_snapshots.snapshot_at` | timestamp | Internal | Time the HTTP `book` response was observed. |
| `orderbook_snapshots.asset_id` | string | CLOB | Outcome token ID. |
| `orderbook_snapshots.condition_id` | string | CLOB | Market/condition ID when available. |
| `orderbook_snapshots.book_hash` | string | CLOB | CLOB book hash when present. |
| `orderbook_top.best_bid/best_ask` | decimal | CLOB/Derived | Top executable bid/ask from finite depth snapshot. |
| `orderbook_top.midpoint` | decimal | Derived | `(best_bid + best_ask) / 2` when both sides exist. |
| `orderbook_top.spread` | decimal | Derived | Best ask minus best bid. |
| `orderbook_top.spread_bps` | decimal | Derived | Spread divided by midpoint, in basis points. |
| `orderbook_top.top_bid_depth/top_ask_depth` | decimal | Derived | Sum of retained size levels per side. |
| `orderbook_top.crossed` | boolean | Derived | True when best ask is below best bid. |
| `orderbook_top.one_sided` | boolean | Derived | True when only bid or ask side exists. |
| `orderbook_depth_snapshots.side` | string | CLOB | `bid` or `ask`. |
| `orderbook_depth_snapshots.level_index` | integer | Derived | One-based depth level after side-aware sorting. |
| `orderbook_depth_snapshots.price/size` | decimal | CLOB | Level price and size. |
| `orderbook_depth_snapshots.cumulative_size` | decimal | Derived | Cumulative size through this level. |
| `orderbook_depth_snapshots.cumulative_notional` | decimal | Derived | Cumulative price * size through this level. |

## Market Stream

| Field | Type | Source | Notes |
|---|---|---|---|
| `market_stream_events.stream_event_uid` | string | Derived | Stable event ID. |
| `market_stream_events.received_at` | timestamp | Internal | System receive time; primary latency reference. |
| `market_stream_events.event_at` | timestamp | CLOB WS | Payload timestamp when present; may be delayed/out of order. |
| `market_stream_events.asset_id` | string | CLOB WS | Outcome token ID when present. |
| `market_stream_events.condition_id` | string | CLOB WS | Market/condition ID when present. |
| `market_stream_events.event_type` | string | CLOB WS | `price_change`, `book`, `last_trade`, `best_bid_ask`, or payload-specific type. |
| `market_stream_events.best_bid/best_ask` | decimal | CLOB/Derived | Parsed from fields or top book levels. |
| `market_stream_events.midpoint/spread` | decimal | Derived | Computed when both sides are available. |
| `market_stream_events.raw` | json | CLOB WS | Full raw WebSocket payload for audit. |

## CLV

| Field | Type | Source | Notes |
|---|---|---|---|
| `reference_price` | decimal | Derived | Prefer delay-adjusted midpoint; fallback to `price_points.price`. |
| `future_price` | decimal | Derived | Future midpoint or price point at target horizon. |
| `clv_30s/2m/10m/1h/24h` | decimal | Derived | `future_price - reference_price` for buys; sign reversed for sells. |
