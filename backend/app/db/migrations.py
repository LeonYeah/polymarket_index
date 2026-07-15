from __future__ import annotations

from sqlalchemy import Engine, text

SCHEMA_VERSION = "2026_07_15_paper_risk_and_resolution_v1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id text PRIMARY KEY,
    job_name text NOT NULL,
    source text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    counters jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    gamma_event_id text PRIMARY KEY,
    ticker text,
    slug text,
    title text,
    description text,
    category text,
    active boolean,
    closed boolean,
    archived boolean,
    start_date timestamptz,
    end_date timestamptz,
    raw jsonb NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS events_slug_idx ON events(slug) WHERE slug IS NOT NULL;

CREATE TABLE IF NOT EXISTS markets (
    condition_id text PRIMARY KEY,
    gamma_market_id text UNIQUE,
    gamma_event_id text REFERENCES events(gamma_event_id),
    slug text,
    question text,
    category text,
    active boolean,
    closed boolean,
    archived boolean,
    accepting_orders boolean,
    end_date timestamptz,
    order_min_size numeric,
    order_price_min_tick_size numeric,
    volume numeric,
    liquidity numeric,
    raw jsonb NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS markets_slug_idx ON markets(slug) WHERE slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS markets_gamma_event_id_idx ON markets(gamma_event_id);

CREATE TABLE IF NOT EXISTS market_tokens (
    token_id text PRIMARY KEY,
    condition_id text NOT NULL REFERENCES markets(condition_id),
    gamma_market_id text,
    outcome_index integer NOT NULL,
    outcome text,
    mapping_status text NOT NULL,
    mapping_error text,
    verified_at timestamptz,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS market_tokens_condition_id_idx ON market_tokens(condition_id);
CREATE INDEX IF NOT EXISTS market_tokens_mapping_status_idx ON market_tokens(mapping_status);

CREATE TABLE IF NOT EXISTS market_liquidity_snapshots (
    id bigserial PRIMARY KEY,
    snapshot_at timestamptz NOT NULL,
    condition_id text,
    gamma_market_id text,
    source_endpoint text NOT NULL,
    open_interest numeric,
    live_volume numeric,
    liquidity numeric,
    volume numeric,
    raw jsonb NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS market_liquidity_snapshots_market_time_idx
    ON market_liquidity_snapshots(condition_id, snapshot_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS market_liquidity_snapshots_run_endpoint_market_idx
    ON market_liquidity_snapshots(ingestion_run_id, source_endpoint, COALESCE(condition_id, ''), COALESCE(gamma_market_id, ''));

ALTER TABLE market_liquidity_snapshots
    DROP CONSTRAINT IF EXISTS market_liquidity_snapshots_condition_id_fkey;

CREATE TABLE IF NOT EXISTS market_holders (
    id bigserial PRIMARY KEY,
    snapshot_at timestamptz NOT NULL,
    condition_id text REFERENCES markets(condition_id),
    token_id text REFERENCES market_tokens(token_id),
    wallet_address text NOT NULL,
    holder_rank integer,
    amount numeric,
    outcome_index integer,
    pseudonym text,
    display_name text,
    verified boolean,
    raw jsonb NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS market_holders_token_time_idx ON market_holders(token_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS market_holders_wallet_idx ON market_holders(wallet_address);
CREATE UNIQUE INDEX IF NOT EXISTS market_holders_run_token_wallet_idx
    ON market_holders(ingestion_run_id, token_id, wallet_address);

CREATE TABLE IF NOT EXISTS raw_api_responses (
    id bigserial PRIMARY KEY,
    source text NOT NULL,
    endpoint text NOT NULL,
    request_params jsonb NOT NULL DEFAULT '{}'::jsonb,
    status_code integer,
    duration_ms integer,
    row_count integer,
    response_hash text NOT NULL,
    response_body jsonb,
    captured_at timestamptz NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS raw_api_responses_run_idx ON raw_api_responses(ingestion_run_id);
CREATE INDEX IF NOT EXISTS raw_api_responses_hash_idx ON raw_api_responses(response_hash);

CREATE TABLE IF NOT EXISTS wallets (
    wallet_address text PRIMARY KEY,
    first_seen_at timestamptz,
    last_seen_at timestamptz,
    active_days_180d integer NOT NULL DEFAULT 0,
    markets_count integer NOT NULL DEFAULT 0,
    resolved_markets_count integer NOT NULL DEFAULT 0,
    notional_30d numeric NOT NULL DEFAULT 0,
    notional_90d numeric NOT NULL DEFAULT 0,
    notional_180d numeric NOT NULL DEFAULT 0,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS wallets_last_seen_idx ON wallets(last_seen_at DESC);

CREATE TABLE IF NOT EXISTS wallet_candidates (
    id bigserial PRIMARY KEY,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    seed_source text NOT NULL,
    seed_ref text,
    discovered_at timestamptz NOT NULL,
    rank integer,
    score numeric,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS wallet_candidates_wallet_idx ON wallet_candidates(wallet_address);
CREATE INDEX IF NOT EXISTS wallet_candidates_seed_source_idx ON wallet_candidates(seed_source);
CREATE UNIQUE INDEX IF NOT EXISTS wallet_candidates_unique_seed_idx
    ON wallet_candidates(wallet_address, seed_source, COALESCE(seed_ref, ''));

CREATE TABLE IF NOT EXISTS trades (
    trade_uid text PRIMARY KEY,
    api_trade_id text,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    proxy_wallet text,
    condition_id text,
    token_id text,
    side text,
    price numeric,
    size numeric,
    notional numeric,
    trade_timestamp timestamptz,
    transaction_hash text,
    taker_only boolean NOT NULL,
    raw jsonb NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS trades_wallet_time_idx ON trades(wallet_address, trade_timestamp DESC);
CREATE INDEX IF NOT EXISTS trades_condition_id_idx ON trades(condition_id);
CREATE INDEX IF NOT EXISTS trades_token_id_idx ON trades(token_id);
CREATE INDEX IF NOT EXISTS trades_transaction_hash_idx ON trades(transaction_hash);

CREATE TABLE IF NOT EXISTS wallet_positions_current (
    position_uid text PRIMARY KEY,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    condition_id text,
    token_id text,
    outcome text,
    size numeric,
    avg_price numeric,
    initial_value numeric,
    current_value numeric,
    cash_pnl numeric,
    realized_pnl numeric,
    cur_price numeric,
    redeemable boolean,
    mergeable boolean,
    title text,
    slug text,
    event_slug text,
    end_date timestamptz,
    snapshot_at timestamptz NOT NULL,
    raw jsonb NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS wallet_positions_current_wallet_idx
    ON wallet_positions_current(wallet_address, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS wallet_positions_closed (
    position_uid text PRIMARY KEY,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    condition_id text,
    token_id text,
    outcome text,
    avg_price numeric,
    total_bought numeric,
    realized_pnl numeric,
    cur_price numeric,
    title text,
    slug text,
    event_slug text,
    end_date timestamptz,
    closed_at timestamptz,
    raw jsonb NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS wallet_positions_closed_wallet_idx
    ON wallet_positions_closed(wallet_address, closed_at DESC);
CREATE INDEX IF NOT EXISTS wallet_positions_closed_condition_idx
    ON wallet_positions_closed(condition_id);

CREATE TABLE IF NOT EXISTS wallet_activity_daily (
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    activity_date date NOT NULL,
    trades_count integer NOT NULL DEFAULT 0,
    markets_count integer NOT NULL DEFAULT 0,
    notional numeric NOT NULL DEFAULT 0,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (wallet_address, activity_date)
);

CREATE TABLE IF NOT EXISTS wallet_backfill_checkpoints (
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    endpoint text NOT NULL,
    taker_only boolean NOT NULL DEFAULT false,
    next_offset integer NOT NULL DEFAULT 0,
    status text NOT NULL,
    last_error text,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (wallet_address, endpoint, taker_only)
);

CREATE TABLE IF NOT EXISTS market_resolution_status (
    condition_id text PRIMARY KEY,
    status text NOT NULL,
    closed boolean,
    active boolean,
    archived boolean,
    resolved_at timestamptz,
    winning_outcome text,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS market_resolution_status_status_idx
    ON market_resolution_status(status);

CREATE TABLE IF NOT EXISTS wallet_market_results (
    result_uid text PRIMARY KEY,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    condition_id text,
    token_id text,
    outcome text,
    market_status text NOT NULL DEFAULT 'unknown',
    result_status text NOT NULL DEFAULT 'unknown',
    outcome_correct boolean,
    trade_count integer NOT NULL DEFAULT 0,
    buy_count integer NOT NULL DEFAULT 0,
    sell_count integer NOT NULL DEFAULT 0,
    taker_trade_count integer NOT NULL DEFAULT 0,
    total_buy_size numeric NOT NULL DEFAULT 0,
    total_sell_size numeric NOT NULL DEFAULT 0,
    total_buy_notional numeric NOT NULL DEFAULT 0,
    total_sell_notional numeric NOT NULL DEFAULT 0,
    avg_buy_price numeric,
    avg_sell_price numeric,
    open_size numeric NOT NULL DEFAULT 0,
    capital_deployed numeric NOT NULL DEFAULT 0,
    realized_pnl numeric NOT NULL DEFAULT 0,
    unrealized_pnl numeric NOT NULL DEFAULT 0,
    current_value numeric NOT NULL DEFAULT 0,
    estimated_fees numeric NOT NULL DEFAULT 0,
    estimated_slippage numeric NOT NULL DEFAULT 0,
    fees_estimated boolean NOT NULL DEFAULT true,
    slippage_estimated boolean NOT NULL DEFAULT true,
    fee_risk_level text NOT NULL DEFAULT 'unknown',
    net_pnl numeric NOT NULL DEFAULT 0,
    gross_roi numeric,
    net_roi numeric,
    entry_time timestamptz,
    exit_time timestamptz,
    holding_duration_seconds bigint,
    calculation_notes jsonb NOT NULL DEFAULT '{}'::jsonb,
    calculated_at timestamptz NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS wallet_market_results_wallet_market_token_idx
    ON wallet_market_results(wallet_address, COALESCE(condition_id, ''), COALESCE(token_id, ''), COALESCE(outcome, ''));
CREATE INDEX IF NOT EXISTS wallet_market_results_wallet_idx
    ON wallet_market_results(wallet_address);
CREATE INDEX IF NOT EXISTS wallet_market_results_condition_idx
    ON wallet_market_results(condition_id);
CREATE INDEX IF NOT EXISTS wallet_market_results_result_status_idx
    ON wallet_market_results(result_status);

CREATE TABLE IF NOT EXISTS wallet_daily_equity (
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    equity_date date NOT NULL,
    realized_pnl_cumulative numeric NOT NULL DEFAULT 0,
    unrealized_pnl numeric NOT NULL DEFAULT 0,
    net_pnl numeric NOT NULL DEFAULT 0,
    capital_deployed numeric NOT NULL DEFAULT 0,
    daily_volume numeric NOT NULL DEFAULT 0,
    trades_count integer NOT NULL DEFAULT 0,
    drawdown numeric NOT NULL DEFAULT 0,
    max_drawdown numeric NOT NULL DEFAULT 0,
    calculated_at timestamptz NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (wallet_address, equity_date)
);

CREATE INDEX IF NOT EXISTS wallet_daily_equity_wallet_date_idx
    ON wallet_daily_equity(wallet_address, equity_date DESC);

CREATE TABLE IF NOT EXISTS pnl_reconciliation_checks (
    id bigserial PRIMARY KEY,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    condition_id text,
    token_id text,
    check_type text NOT NULL,
    status text NOT NULL,
    diff_category text NOT NULL,
    engine_realized_pnl numeric,
    source_realized_pnl numeric,
    difference numeric,
    tolerance numeric NOT NULL DEFAULT 0,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    checked_at timestamptz NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pnl_reconciliation_wallet_idx
    ON pnl_reconciliation_checks(wallet_address, checked_at DESC);
CREATE INDEX IF NOT EXISTS pnl_reconciliation_status_idx
    ON pnl_reconciliation_checks(status, diff_category);

CREATE TABLE IF NOT EXISTS price_points (
    id bigserial PRIMARY KEY,
    asset_id text NOT NULL,
    condition_id text,
    price_at timestamptz NOT NULL,
    price numeric NOT NULL,
    source_endpoint text NOT NULL,
    interval text,
    fidelity integer,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS price_points_asset_time_source_idx
    ON price_points(asset_id, price_at, source_endpoint, COALESCE(interval, ''), COALESCE(fidelity, -1));
CREATE INDEX IF NOT EXISTS price_points_condition_time_idx
    ON price_points(condition_id, price_at DESC);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    snapshot_uid text PRIMARY KEY,
    snapshot_at timestamptz NOT NULL,
    asset_id text NOT NULL,
    condition_id text,
    book_hash text,
    min_order_size numeric,
    tick_size numeric,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_endpoint text NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS orderbook_snapshots_asset_time_idx
    ON orderbook_snapshots(asset_id, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS orderbook_top (
    snapshot_uid text PRIMARY KEY REFERENCES orderbook_snapshots(snapshot_uid) ON DELETE CASCADE,
    snapshot_at timestamptz NOT NULL,
    asset_id text NOT NULL,
    condition_id text,
    best_bid numeric,
    best_bid_size numeric,
    best_ask numeric,
    best_ask_size numeric,
    midpoint numeric,
    spread numeric,
    spread_bps numeric,
    top_bid_depth numeric NOT NULL DEFAULT 0,
    top_ask_depth numeric NOT NULL DEFAULT 0,
    crossed boolean NOT NULL DEFAULT false,
    one_sided boolean NOT NULL DEFAULT false,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS orderbook_top_asset_time_idx
    ON orderbook_top(asset_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS orderbook_top_spread_idx
    ON orderbook_top(spread DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS orderbook_depth_snapshots (
    snapshot_uid text NOT NULL REFERENCES orderbook_snapshots(snapshot_uid) ON DELETE CASCADE,
    snapshot_at timestamptz NOT NULL,
    asset_id text NOT NULL,
    condition_id text,
    side text NOT NULL,
    level_index integer NOT NULL,
    price numeric NOT NULL,
    size numeric NOT NULL,
    notional numeric NOT NULL,
    cumulative_size numeric NOT NULL,
    cumulative_notional numeric NOT NULL,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_uid, side, level_index)
);

CREATE INDEX IF NOT EXISTS orderbook_depth_asset_side_time_idx
    ON orderbook_depth_snapshots(asset_id, side, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS market_stream_events (
    stream_event_uid text PRIMARY KEY,
    received_at timestamptz NOT NULL,
    event_at timestamptz,
    asset_id text,
    condition_id text,
    event_type text NOT NULL,
    book_hash text,
    best_bid numeric,
    best_ask numeric,
    midpoint numeric,
    spread numeric,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS market_stream_events_asset_received_idx
    ON market_stream_events(asset_id, received_at DESC);
CREATE INDEX IF NOT EXISTS market_stream_events_type_idx
    ON market_stream_events(event_type);

CREATE TABLE IF NOT EXISTS market_followability_snapshots (
    snapshot_uid text PRIMARY KEY REFERENCES orderbook_snapshots(snapshot_uid) ON DELETE CASCADE,
    snapshot_at timestamptz NOT NULL,
    asset_id text NOT NULL,
    condition_id text,
    spread numeric,
    spread_bps numeric,
    top_bid_depth numeric NOT NULL DEFAULT 0,
    top_ask_depth numeric NOT NULL DEFAULT 0,
    estimated_buy_slippage numeric,
    estimated_sell_slippage numeric,
    buy_fillable boolean NOT NULL DEFAULT false,
    sell_fillable boolean NOT NULL DEFAULT false,
    spread_too_wide boolean NOT NULL DEFAULT false,
    depth_insufficient boolean NOT NULL DEFAULT false,
    price_missing boolean NOT NULL DEFAULT false,
    market_liquidity_score numeric,
    signal_to_snapshot_delay_seconds bigint,
    notes jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS market_followability_asset_time_idx
    ON market_followability_snapshots(asset_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS market_followability_flags_idx
    ON market_followability_snapshots(spread_too_wide, depth_insufficient, price_missing);

CREATE TABLE IF NOT EXISTS trade_clv_metrics (
    trade_uid text PRIMARY KEY REFERENCES trades(trade_uid) ON DELETE CASCADE,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    condition_id text,
    token_id text,
    side text,
    trade_timestamp timestamptz NOT NULL,
    trade_price numeric,
    reference_price numeric,
    reference_source text,
    reference_at timestamptz,
    signal_to_reference_delay_seconds bigint,
    clv_30s numeric,
    clv_2m numeric,
    clv_10m numeric,
    clv_1h numeric,
    clv_24h numeric,
    future_price_30s numeric,
    future_price_2m numeric,
    future_price_10m numeric,
    future_price_1h numeric,
    future_price_24h numeric,
    missing_reason text,
    calculated_at timestamptz NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS trade_clv_wallet_time_idx
    ON trade_clv_metrics(wallet_address, trade_timestamp DESC);
CREATE INDEX IF NOT EXISTS trade_clv_token_time_idx
    ON trade_clv_metrics(token_id, trade_timestamp DESC);

CREATE TABLE IF NOT EXISTS wallet_features (
    feature_uid text PRIMARY KEY,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    feature_version text NOT NULL,
    as_of timestamptz NOT NULL,
    observation_start timestamptz NOT NULL,
    observation_end timestamptz NOT NULL,
    n_resolved integer NOT NULL DEFAULT 0,
    active_days_180d integer NOT NULL DEFAULT 0,
    realized_notional_180d numeric NOT NULL DEFAULT 0,
    realized_pnl_180d numeric NOT NULL DEFAULT 0,
    open_unrealized_pnl numeric NOT NULL DEFAULT 0,
    capital_deployed_180d numeric NOT NULL DEFAULT 0,
    net_roi_180d numeric,
    gross_profit_180d numeric NOT NULL DEFAULT 0,
    gross_loss_180d numeric NOT NULL DEFAULT 0,
    profit_factor numeric,
    win_rate numeric,
    bayes_wr numeric,
    max_drawdown numeric NOT NULL DEFAULT 0,
    max_drawdown_ratio numeric,
    single_market_pnl_share numeric,
    avg_clv_30s numeric,
    avg_clv_2m numeric,
    avg_clv_10m numeric,
    avg_clv_1h numeric,
    avg_clv_24h numeric,
    positive_clv_share numeric,
    clv_sample_count integer NOT NULL DEFAULT 0,
    avg_followability numeric,
    low_liquidity_trade_share numeric,
    input_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    calculated_at timestamptz NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (wallet_address, feature_version, as_of)
);

CREATE INDEX IF NOT EXISTS wallet_features_wallet_asof_idx
    ON wallet_features(wallet_address, as_of DESC);
CREATE INDEX IF NOT EXISTS wallet_features_quality_idx
    ON wallet_features(n_resolved DESC, bayes_wr DESC, net_roi_180d DESC);

CREATE TABLE IF NOT EXISTS wallet_scores (
    score_uid text PRIMARY KEY,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    feature_uid text NOT NULL REFERENCES wallet_features(feature_uid) ON DELETE CASCADE,
    score_version text NOT NULL,
    score numeric NOT NULL,
    raw_score numeric NOT NULL,
    confidence numeric NOT NULL,
    high_confidence_eligible boolean NOT NULL DEFAULT false,
    hard_gate_status jsonb NOT NULL DEFAULT '{}'::jsonb,
    exclusion_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    penalty_summary jsonb NOT NULL DEFAULT '[]'::jsonb,
    component_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    weight_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    scored_at timestamptz NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (wallet_address, score_version, scored_at)
);

CREATE INDEX IF NOT EXISTS wallet_scores_rank_idx
    ON wallet_scores(score_version, score DESC, confidence DESC);
CREATE INDEX IF NOT EXISTS wallet_scores_eligible_idx
    ON wallet_scores(high_confidence_eligible, score DESC);

CREATE TABLE IF NOT EXISTS wallet_score_components (
    score_uid text NOT NULL REFERENCES wallet_scores(score_uid) ON DELETE CASCADE,
    component_name text NOT NULL,
    component_score numeric NOT NULL,
    max_score numeric NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (score_uid, component_name)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    backtest_run_uid text PRIMARY KEY,
    score_version text NOT NULL,
    training_start timestamptz NOT NULL,
    training_end timestamptz NOT NULL,
    validation_start timestamptz NOT NULL,
    validation_end timestamptz NOT NULL,
    strategy_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS backtest_wallet_results (
    result_uid text PRIMARY KEY,
    backtest_run_uid text NOT NULL REFERENCES backtest_runs(backtest_run_uid) ON DELETE CASCADE,
    wallet_address text NOT NULL REFERENCES wallets(wallet_address),
    strategy text NOT NULL,
    strategy_rank integer NOT NULL,
    training_score numeric,
    training_confidence numeric,
    training_features jsonb NOT NULL DEFAULT '{}'::jsonb,
    future_realized_pnl numeric NOT NULL DEFAULT 0,
    future_net_pnl numeric NOT NULL DEFAULT 0,
    future_capital_deployed numeric NOT NULL DEFAULT 0,
    future_roi numeric,
    future_avg_clv_10m numeric,
    future_max_drawdown numeric,
    selected_at timestamptz NOT NULL,
    source text NOT NULL,
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS backtest_wallet_results_run_strategy_idx
    ON backtest_wallet_results(backtest_run_uid, strategy, strategy_rank);

CREATE TABLE IF NOT EXISTS watchlist_wallets (
    wallet_address text PRIMARY KEY,
    label text,
    reason text,
    status text NOT NULL DEFAULT 'active',
    operator text NOT NULL DEFAULT 'local',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    added_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS watchlist_wallets_status_idx
    ON watchlist_wallets(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS watchlist_markets (
    condition_id text PRIMARY KEY,
    label text,
    reason text,
    status text NOT NULL DEFAULT 'active',
    operator text NOT NULL DEFAULT 'local',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    added_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS watchlist_markets_status_idx
    ON watchlist_markets(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS watchlist_audit_log (
    id bigserial PRIMARY KEY,
    target_type text NOT NULL,
    target_id text NOT NULL,
    action text NOT NULL,
    operator text NOT NULL DEFAULT 'local',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS watchlist_audit_target_idx
    ON watchlist_audit_log(target_type, target_id, created_at DESC);

CREATE TABLE IF NOT EXISTS alert_events (
    alert_id text PRIMARY KEY,
    alert_type text NOT NULL,
    severity text NOT NULL DEFAULT 'info',
    status text NOT NULL DEFAULT 'open',
    wallet_address text,
    condition_id text,
    token_id text,
    title text NOT NULL,
    message text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    acknowledged_at timestamptz,
    resolved_at timestamptz,
    operator text,
    source text NOT NULL DEFAULT 'dashboard_rules_v1',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS alert_events_status_idx
    ON alert_events(status, severity, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS alert_events_market_idx
    ON alert_events(condition_id, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS alert_events_wallet_idx
    ON alert_events(wallet_address, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS signals (
    signal_id text PRIMARY KEY,
    source_trade_uid text REFERENCES trades(trade_uid),
    leader_wallet text NOT NULL REFERENCES wallets(wallet_address),
    market_id text NOT NULL,
    token_id text NOT NULL,
    side text NOT NULL CHECK (side IN ('BUY', 'SELL')),
    leader_price numeric NOT NULL,
    leader_size numeric NOT NULL,
    leader_trade_time timestamptz NOT NULL,
    detected_at timestamptz NOT NULL,
    confidence numeric NOT NULL,
    wallet_weight numeric NOT NULL,
    reason text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    processing_status text NOT NULL DEFAULT 'pending'
        CHECK (processing_status IN ('pending', 'merged', 'ordered', 'rejected')),
    parent_signal_id text REFERENCES signals(signal_id),
    source text NOT NULL DEFAULT 'signal_engine_v1',
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS signals_source_trade_wallet_idx
    ON signals(source_trade_uid, leader_wallet) WHERE source_trade_uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS signals_market_detected_idx
    ON signals(market_id, token_id, side, detected_at DESC);
CREATE INDEX IF NOT EXISTS signals_status_idx
    ON signals(processing_status, detected_at DESC);

CREATE TABLE IF NOT EXISTS paper_orders (
    order_id text PRIMARY KEY,
    signal_id text NOT NULL REFERENCES signals(signal_id),
    strategy_version text NOT NULL,
    order_type text NOT NULL CHECK (order_type IN ('FOK', 'FAK', 'GTC')),
    side text NOT NULL CHECK (side IN ('BUY', 'SELL')),
    market_id text NOT NULL,
    token_id text NOT NULL,
    requested_size numeric NOT NULL CHECK (requested_size > 0),
    requested_notional numeric NOT NULL CHECK (requested_notional >= 0),
    worst_price numeric NOT NULL,
    estimated_fill_price numeric,
    filled_size numeric NOT NULL DEFAULT 0,
    estimated_slippage numeric NOT NULL DEFAULT 0,
    estimated_fee numeric NOT NULL DEFAULT 0,
    status text NOT NULL CHECK (
        status IN ('created', 'rejected', 'would_fill', 'would_partial_fill', 'expired', 'settled')
    ),
    reject_reason text CHECK (
        reject_reason IS NULL OR reject_reason IN (
            'insufficient_score', 'low_confidence', 'low_liquidity', 'wide_spread',
            'stale_data', 'late_signal', 'market_not_accepting_orders',
            'compliance_block', 'negative_expected_edge', 'token_exposure_limit'
        )
    ),
    leader_trade_time timestamptz NOT NULL,
    signal_detected_at timestamptz NOT NULL,
    decision_at timestamptz NOT NULL,
    order_simulated_at timestamptz NOT NULL,
    detection_latency_ms bigint NOT NULL DEFAULT 0,
    decision_latency_ms bigint NOT NULL DEFAULT 0,
    simulation_latency_ms bigint NOT NULL DEFAULT 0,
    orderbook_snapshot_uid text REFERENCES orderbook_snapshots(snapshot_uid),
    decision_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL DEFAULT 'paper_trading_engine_v1',
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (signal_id, strategy_version, order_type)
);

CREATE INDEX IF NOT EXISTS paper_orders_status_idx
    ON paper_orders(status, order_simulated_at DESC);
CREATE INDEX IF NOT EXISTS paper_orders_market_idx
    ON paper_orders(market_id, token_id, order_simulated_at DESC);

CREATE TABLE IF NOT EXISTS paper_order_events (
    event_id text PRIMARY KEY,
    order_id text NOT NULL REFERENCES paper_orders(order_id) ON DELETE CASCADE,
    from_status text,
    to_status text NOT NULL,
    event_at timestamptz NOT NULL,
    reason text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL DEFAULT 'paper_trading_engine_v1',
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS paper_order_events_order_time_idx
    ON paper_order_events(order_id, event_at);

CREATE TABLE IF NOT EXISTS paper_positions (
    position_id text PRIMARY KEY,
    strategy_version text NOT NULL,
    market_id text NOT NULL,
    token_id text NOT NULL,
    side text NOT NULL CHECK (side IN ('BUY', 'SELL')),
    size numeric NOT NULL,
    average_entry_price numeric NOT NULL,
    cost_basis numeric NOT NULL,
    accumulated_fee numeric NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'settled')),
    opened_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    settled_at timestamptz,
    source text NOT NULL DEFAULT 'paper_trading_engine_v1',
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (strategy_version, market_id, token_id, side)
);

CREATE INDEX IF NOT EXISTS paper_positions_status_idx
    ON paper_positions(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS paper_pnl (
    pnl_id text PRIMARY KEY,
    order_id text NOT NULL REFERENCES paper_orders(order_id) ON DELETE CASCADE,
    strategy_version text NOT NULL,
    market_id text NOT NULL,
    token_id text NOT NULL,
    valuation_type text NOT NULL CHECK (valuation_type IN ('mark_to_market', 'settled')),
    entry_price numeric NOT NULL,
    exit_price numeric NOT NULL,
    filled_size numeric NOT NULL,
    gross_pnl numeric NOT NULL,
    fee numeric NOT NULL,
    slippage_cost numeric NOT NULL,
    net_pnl numeric NOT NULL,
    direction_correct boolean,
    profitable_after_costs boolean NOT NULL,
    valued_at timestamptz NOT NULL,
    attribution jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL DEFAULT 'paper_pnl_v1',
    ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (order_id, valuation_type, valued_at)
);

CREATE INDEX IF NOT EXISTS paper_pnl_strategy_time_idx
    ON paper_pnl(strategy_version, valued_at DESC);

ALTER TABLE paper_orders DROP CONSTRAINT IF EXISTS paper_orders_reject_reason_check;
ALTER TABLE paper_orders ADD CONSTRAINT paper_orders_reject_reason_check CHECK (
    reject_reason IS NULL OR reject_reason IN (
        'insufficient_score', 'low_confidence', 'low_liquidity', 'wide_spread',
        'stale_data', 'late_signal', 'market_not_accepting_orders',
        'compliance_block', 'negative_expected_edge', 'token_exposure_limit'
    )
);
"""


def apply_schema(engine: Engine) -> None:
    statements = [statement.strip() for statement in SCHEMA_SQL.split(";") if statement.strip()]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text(
                """
                INSERT INTO schema_migrations(version)
                VALUES (:version)
                ON CONFLICT (version) DO NOTHING
                """
            ),
            {"version": SCHEMA_VERSION},
        )
