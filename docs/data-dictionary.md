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

## Followability

| Field | Type | Source | Notes |
|---|---|---|---|
| `market_followability_snapshots.snapshot_uid` | string | Derived | Same ID as the source order book snapshot. |
| `market_followability_snapshots.estimated_buy_slippage` | decimal | Derived | Conservative buy-side slippage for configured size. |
| `market_followability_snapshots.estimated_sell_slippage` | decimal | Derived | Conservative sell-side slippage for configured size. |
| `market_followability_snapshots.buy_fillable/sell_fillable` | boolean | Derived | Whether retained depth can fill configured size. |
| `market_followability_snapshots.spread_too_wide` | boolean | Derived | True when spread bps exceeds configured threshold. |
| `market_followability_snapshots.depth_insufficient` | boolean | Derived | True when either side cannot fill configured size. |
| `market_followability_snapshots.price_missing` | boolean | Derived | True when top bid, ask, or midpoint is unavailable. |
| `market_followability_snapshots.market_liquidity_score` | decimal | Derived | 0-100 conservative score from spread and retained depth. |
| `market_followability_snapshots.signal_to_snapshot_delay_seconds` | integer | Derived | Optional signal-to-snapshot delay when a signal time is supplied. |

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
| `trade_clv_metrics.reference_source` | string | Derived | `orderbook_midpoint` preferred; `price_history` fallback. |
| `trade_clv_metrics.missing_reason` | string | Derived | `missing_reference_price` or `missing_future_prices` when CLV cannot be computed. |

## SmartScore Feature

| Field | Type | Source | Notes |
|---|---|---|---|
| `feature_uid` | string | Derived | Stable hash over wallet, feature version, and scoring cutoff. |
| `feature_version` | string | Internal | Versioned feature contract, currently `wallet_features_v1`. |
| `as_of` | timestamp | Internal | Scoring cutoff; feature queries must not read later observations. |
| `observation_start/end` | timestamp | Internal | Training observation window, v1 defaults to 180 days. |
| `n_resolved` | integer | `wallet_market_results` | Closed or settled market-result count in the observation window. |
| `active_days_180d` | integer | `trades` | Distinct UTC trade days in the observation window. |
| `realized_notional_180d` | decimal | `trades` | Sum of trade notional in the observation window; used for hard gate. |
| `realized_pnl_180d` | decimal | `wallet_market_results` | Sum of realized PnL from closed or settled result rows. |
| `net_roi_180d` | decimal | Derived | `(realized_pnl + open_unrealized_pnl) / capital_deployed_180d`; open PnL remains separately visible. |
| `bayes_wr` | decimal | Derived | Bayesian win rate with 55% neutral prior from wins/losses. |
| `max_drawdown_ratio` | decimal | Derived | Latest daily max drawdown divided by observation-window capital deployed. |
| `single_market_pnl_share` | decimal | Derived | Best single-market realized PnL divided by gross profit. |
| `avg_clv_*` | decimal | `trade_clv_metrics` | Average signed CLV by horizon where data exists. |
| `avg_followability` | decimal | `market_followability_snapshots` | Latest pre-trade liquidity score by token, averaged per wallet. |
| `input_snapshot` | json | Internal | Source table list and parameters needed for reproducibility. |

## Wallet Score

| Field | Type | Source | Notes |
|---|---|---|---|
| `score_uid` | string | Derived | Stable hash over wallet, score version, and scoring time. |
| `score_version` | string | Internal | Versioned scoring contract; current writes use `smart_score_v2`, while v1 rows remain auditable. |
| `score` | decimal | Derived | Final 0-100 score after caps and penalties. |
| `raw_score` | decimal | Derived | Component sum before caps and penalties. |
| `confidence` | decimal | Derived | 0-1 confidence from sample size, activity, followability, CLV coverage, and unrealized-PnL concentration. |
| `high_confidence_eligible` | boolean | Derived | True only when all hard gates pass. |
| `hard_gate_status` | json | Derived | V2 per-gate status for resolved count, activity, notional, ROI, Bayesian WR, drawdown, and followability. Market concentration remains a soft penalty, not an eligibility gate. |
| `exclusion_reasons` | json | Derived | Failed gate names. |
| `penalty_summary` | json | Derived | Score caps and deductions, including small sample and single-market concentration. |
| `weight_config` | json | Internal | Component weights used for reproducible scoring. |

## Backtest

| Field | Type | Source | Notes |
|---|---|---|---|
| `backtest_runs.training_start/end` | timestamp | Internal | Observation window used to select wallets. |
| `backtest_runs.validation_start/end` | timestamp | Internal | Future window used to compare selected wallets. |
| `strategy` | enum | Derived | V1 strategies: `top_score`, `top_pnl`, `random_active`. |
| `training_score` | decimal | `wallet_scores` | Score at training cutoff. |
| `training_features` | json | `wallet_features` | Feature snapshot used for selection audit. |
| `future_net_pnl` | decimal | `wallet_market_results` | Future-window net PnL for the selected wallet. |
| `future_roi` | decimal | Derived | Future net PnL divided by future capital deployed. |
| `future_avg_clv_10m` | decimal | `trade_clv_metrics` | Future-window average 10-minute CLV where available. |

## Paper Trading Signal

| Field | Type | Source | Notes |
|---|---|---|---|
| `signal_id` | string | Derived | Stable hash of engine version, source trade, and leader wallet; merged signals hash all child IDs. |
| `source_trade_uid` | string | `trades` | Original public trade row; null only for an aligned multi-wallet merged signal. |
| `leader_wallet` | string | `trades` | Wallet that produced the trade; merged signals retain all leaders in evidence. |
| `market_id/token_id` | string | `trades` | Condition and outcome token mapping used for book lookup. |
| `leader_price/leader_size` | decimal | `trades` | Observed leader fill, not the assumed follower fill. |
| `leader_trade_time/detected_at` | timestamp | Source/Internal | UTC timestamps used for detection latency. |
| `confidence` | decimal | `wallet_scores` | Latest wallet confidence; low confidence remains rejectable even for watchlists. |
| `wallet_weight` | decimal | Derived | 0-1 weighted combination of SmartScore, category proxy, stability, and followability. |
| `reason` | enum | Derived | `high_score_wallet_trade`, `watchlist_wallet_trade`, or `aligned_wallet_signals_merged`. |
| `processing_status` | enum | Internal | `pending`, `merged`, `ordered`, or `rejected`. |
| `parent_signal_id` | string | Derived | Merged parent signal, preserving child-to-parent auditability. |

## Paper Order and Lifecycle

| Field | Type | Source | Notes |
|---|---|---|---|
| `order_type` | enum | Strategy | `FOK`, `FAK`, or `GTC`; simulation only. |
| `status` | enum | Engine | `created`, `rejected`, `would_fill`, `would_partial_fill`, `expired`, or `settled`. |
| `requested_size/notional` | decimal | Derived | Weight-scaled request, bounded by strategy min/max notional. |
| `worst_price` | decimal | Derived | Limit used while walking archived book levels. |
| `estimated_fill_price/filled_size` | decimal | Order book | Size-weighted simulated result; never defaults to full fill. |
| `estimated_slippage` | decimal | Derived | Side-aware difference between midpoint/reference and simulated average fill. |
| `estimated_fee` | decimal | Derived | Filled notional times the versioned fee assumption. |
| `reject_reason` | enum | Risk gates | One of the nine Week08 reasons; never free-form for a rejected order. |
| `detection_latency_ms` | integer | Derived | Leader trade time to signal detection. |
| `decision_latency_ms` | integer | Derived | Signal detection to strategy decision. |
| `simulation_latency_ms` | integer | Derived | Strategy decision to book simulation completion. |
| `paper_order_events` | lifecycle | Internal | Append-only transition evidence including create/reject/fill, GTC expiry, and settlement. |

## Paper Position and PnL

| Field | Type | Source | Notes |
|---|---|---|---|
| `paper_positions.average_entry_price` | decimal | Paper fills | Size-weighted entry price for a strategy/market/token/side. |
| `paper_positions.cost_basis` | decimal | Derived | Simulated fill price times size; fees remain separate. |
| `valuation_type` | enum | Derived | `mark_to_market` from latest midpoint or `settled` from final outcome. |
| `gross_pnl` | decimal | Derived | Side-aware exit minus entry value before costs. |
| `fee` | decimal | Paper order | Estimated transaction fee assigned to the order. |
| `slippage_cost` | decimal | Derived | Absolute paper entry versus observed leader price, times filled size. |
| `net_pnl` | decimal | Derived | Gross PnL minus estimated fee; slippage is already embedded in paper entry. |
| `direction_correct` | boolean | Derived | Whether price/outcome moved in the leader's direction. |
| `profitable_after_costs` | boolean | Derived | Whether net PnL is positive; kept separate from direction correctness. |
