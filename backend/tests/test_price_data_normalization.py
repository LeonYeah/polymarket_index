from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.collectors.price_data import (
    calculate_clv,
    calculate_trade_clv,
    estimate_slippage,
    normalize_book_side,
    normalize_orderbook,
    normalize_price_history,
    normalize_stream_event,
)


def test_normalize_price_history_supports_clob_history_shape() -> None:
    rows = normalize_price_history(
        {"history": [{"t": 1_788_249_600, "p": "0.42"}]},
        asset_id="111",
        run_id="run-1",
        interval="1d",
        fidelity=None,
    )

    assert rows[0]["asset_id"] == "111"
    assert rows[0]["price_at"] == datetime(2026, 9, 1, 8, tzinfo=UTC)
    assert rows[0]["price"] == Decimal("0.42")
    assert rows[0]["source_endpoint"] == "clob.prices-history"


def test_normalize_orderbook_calculates_top_spread_and_depth() -> None:
    snapshot, top, depth_rows = normalize_orderbook(
        {
            "market": "0xmarket",
            "asset_id": "111",
            "timestamp": "1788249600000",
            "hash": "abc",
            "bids": [{"price": "0.41", "size": "10"}, {"price": "0.40", "size": "5"}],
            "asks": [{"price": "0.43", "size": "8"}, {"price": "0.44", "size": "7"}],
            "min_order_size": "1",
            "tick_size": "0.01",
        },
        run_id="run-1",
        snapshot_at=datetime(2026, 9, 1, tzinfo=UTC),
        depth_limit=2,
    )

    assert snapshot["asset_id"] == "111"
    assert top["best_bid"] == Decimal("0.41")
    assert top["best_ask"] == Decimal("0.43")
    assert top["midpoint"] == Decimal("0.42")
    assert top["spread"] == Decimal("0.02")
    assert top["top_bid_depth"] == Decimal("15")
    assert top["top_ask_depth"] == Decimal("15")
    assert len(depth_rows) == 4
    assert depth_rows[0]["side"] == "bid"
    assert depth_rows[0]["cumulative_notional"] == Decimal("4.10")


def test_normalize_stream_event_preserves_received_and_event_time() -> None:
    row = normalize_stream_event(
        {
            "event_type": "book",
            "asset_id": "111",
            "market": "0xmarket",
            "timestamp": "1788249600000",
            "hash": "abc",
            "bids": [{"price": "0.40", "size": "10"}],
            "asks": [{"price": "0.44", "size": "10"}],
        },
        run_id="run-1",
        received_at=datetime(2026, 9, 1, 0, 0, 1, tzinfo=UTC),
    )

    assert row["received_at"] == datetime(2026, 9, 1, 0, 0, 1, tzinfo=UTC)
    assert row["event_at"] == datetime(2026, 9, 1, 8, tzinfo=UTC)
    assert row["midpoint"] == Decimal("0.42")
    assert row["spread"] == Decimal("0.04")


def test_calculate_clv_adjusts_sign_by_trade_side() -> None:
    assert calculate_clv(
        side="BUY",
        reference_price=Decimal("0.40"),
        future_price=Decimal("0.45"),
    ) == Decimal("0.05")
    assert calculate_clv(
        side="SELL",
        reference_price=Decimal("0.40"),
        future_price=Decimal("0.45"),
    ) == Decimal("-0.05")


def test_calculate_trade_clv_ignores_pre_trade_future_points() -> None:
    trade_timestamp = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    clv = calculate_trade_clv(
        side="BUY",
        trade_timestamp=trade_timestamp,
        reference_price=Decimal("0.40"),
        future_prices={
            "clv_30s": (datetime(2026, 9, 1, 0, 0, 30, tzinfo=UTC), Decimal("0.43")),
            "clv_2m": (datetime(2026, 8, 31, 23, 59, tzinfo=UTC), Decimal("0.39")),
            "clv_10m": None,
        },
    )

    assert clv["clv_30s"] == Decimal("0.03")
    assert clv["clv_2m"] is None
    assert clv["clv_10m"] is None


def test_estimate_slippage_uses_book_depth_conservatively() -> None:
    ask_levels = normalize_book_side(
        [{"price": "0.40", "size": "5"}, {"price": "0.42", "size": "5"}],
        side="ask",
    )
    result = estimate_slippage(side="BUY", size=Decimal("10"), levels=ask_levels)

    assert result["filled"] is True
    assert result["avg_price"] == Decimal("0.41")
    assert result["slippage"] == Decimal("0.01")
