from backend.app.db.migrations import SCHEMA_SQL


def test_week02_schema_contains_required_tables() -> None:
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


def test_week02_schema_preserves_raw_json_and_run_id() -> None:
    assert "raw jsonb NOT NULL" in SCHEMA_SQL
    assert "ingestion_run_id text NOT NULL REFERENCES ingestion_runs(run_id)" in SCHEMA_SQL
