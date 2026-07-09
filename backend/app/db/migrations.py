from __future__ import annotations

from sqlalchemy import Engine, text

SCHEMA_VERSION = "2026_07_09_week02_schema_v1"

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
