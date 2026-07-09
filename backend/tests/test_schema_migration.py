from backend.app.db.migrations import SCHEMA_SQL


def test_schema_contains_week02_required_tables() -> None:
    for table_name in [
        "ingestion_runs",
        "events",
        "markets",
        "market_tokens",
        "market_liquidity_snapshots",
        "market_holders",
        "raw_api_responses",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SCHEMA_SQL


def test_schema_preserves_raw_json_and_run_id() -> None:
    assert "raw jsonb NOT NULL" in SCHEMA_SQL
    assert "ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id)" in SCHEMA_SQL


def test_schema_contains_week03_wallet_tables() -> None:
    for table_name in [
        "wallets",
        "wallet_candidates",
        "trades",
        "wallet_positions_current",
        "wallet_positions_closed",
        "wallet_activity_daily",
        "wallet_backfill_checkpoints",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SCHEMA_SQL


def test_schema_records_trade_uniqueness_and_checkpoint_resume() -> None:
    assert "trade_uid text PRIMARY KEY" in SCHEMA_SQL
    assert "PRIMARY KEY (wallet_address, endpoint, taker_only)" in SCHEMA_SQL
