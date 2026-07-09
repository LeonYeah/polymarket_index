from __future__ import annotations

from sqlalchemy import Engine, text

SCHEMA_VERSION = "2026_07_09_week04_pnl_schema_v1"

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
