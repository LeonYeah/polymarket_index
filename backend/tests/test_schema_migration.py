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


def test_schema_contains_week04_pnl_tables() -> None:
    for table_name in [
        "wallet_market_results",
        "wallet_daily_equity",
        "pnl_reconciliation_checks",
        "market_resolution_status",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SCHEMA_SQL


def test_schema_keeps_realized_and_unrealized_pnl_separate() -> None:
    assert "realized_pnl numeric NOT NULL DEFAULT 0" in SCHEMA_SQL
    assert "unrealized_pnl numeric NOT NULL DEFAULT 0" in SCHEMA_SQL
    assert "current_value numeric NOT NULL DEFAULT 0" in SCHEMA_SQL


def test_schema_contains_week05_price_archive_tables() -> None:
    for table_name in [
        "price_points",
        "orderbook_snapshots",
        "orderbook_top",
        "orderbook_depth_snapshots",
        "market_stream_events",
        "market_followability_snapshots",
        "trade_clv_metrics",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SCHEMA_SQL


def test_schema_records_received_at_for_market_stream_events() -> None:
    assert "received_at timestamptz NOT NULL" in SCHEMA_SQL
    assert "event_at timestamptz" in SCHEMA_SQL


def test_schema_contains_week06_smart_score_tables() -> None:
    for table_name in [
        "wallet_features",
        "wallet_scores",
        "wallet_score_components",
        "backtest_runs",
        "backtest_wallet_results",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SCHEMA_SQL


def test_schema_records_score_reproducibility_fields() -> None:
    assert "score_version text NOT NULL" in SCHEMA_SQL
    assert "weight_config jsonb NOT NULL DEFAULT '{}'::jsonb" in SCHEMA_SQL
    assert "input_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb" in SCHEMA_SQL
    assert "hard_gate_status jsonb NOT NULL DEFAULT '{}'::jsonb" in SCHEMA_SQL


def test_schema_contains_week07_dashboard_alert_tables() -> None:
    for table_name in [
        "watchlist_wallets",
        "watchlist_markets",
        "watchlist_audit_log",
        "alert_events",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SCHEMA_SQL


def test_schema_records_alert_lifecycle_and_watchlist_audit() -> None:
    assert "status text NOT NULL DEFAULT 'open'" in SCHEMA_SQL
    assert "acknowledged_at timestamptz" in SCHEMA_SQL
    assert "resolved_at timestamptz" in SCHEMA_SQL
    assert "target_type text NOT NULL" in SCHEMA_SQL
    assert "operator text NOT NULL DEFAULT 'local'" in SCHEMA_SQL


def test_schema_contains_week08_paper_trading_tables() -> None:
    for table_name in [
        "signals",
        "paper_orders",
        "paper_order_events",
        "paper_positions",
        "paper_pnl",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SCHEMA_SQL


def test_schema_records_paper_lifecycle_latency_and_reject_reasons() -> None:
    for status in [
        "created",
        "rejected",
        "would_fill",
        "would_partial_fill",
        "expired",
        "settled",
    ]:
        assert f"'{status}'" in SCHEMA_SQL
    for reason in [
        "insufficient_score",
        "low_confidence",
        "low_liquidity",
        "wide_spread",
        "stale_data",
        "late_signal",
        "market_metadata_missing",
        "market_not_accepting_orders",
        "compliance_block",
        "negative_expected_edge",
        "token_exposure_limit",
    ]:
        assert f"'{reason}'" in SCHEMA_SQL
    assert "detection_latency_ms bigint" in SCHEMA_SQL
    assert "decision_latency_ms bigint" in SCHEMA_SQL
    assert "simulation_latency_ms bigint" in SCHEMA_SQL
