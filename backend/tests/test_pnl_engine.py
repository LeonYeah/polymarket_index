from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.analytics.pnl_engine import PnLInput, calculate_wallet_pnl, summarize_wallet_profile


def test_pnl_keeps_unrealized_values_out_of_realized_pnl() -> None:
    result = calculate_wallet_pnl(
        PnLInput(
            wallet_address="0xabc",
            trades=[
                {
                    "wallet_address": "0xabc",
                    "condition_id": "0xmarket",
                    "token_id": "111",
                    "outcome": "Yes",
                    "side": "BUY",
                    "price": Decimal("0.40"),
                    "size": Decimal("10"),
                    "notional": Decimal("4.0"),
                    "trade_timestamp": datetime(2026, 7, 1, tzinfo=UTC),
                    "raw": {},
                }
            ],
            current_positions=[
                {
                    "condition_id": "0xmarket",
                    "token_id": "111",
                    "outcome": "Yes",
                    "size": Decimal("10"),
                    "current_value": Decimal("7.0"),
                    "cash_pnl": Decimal("3.0"),
                    "realized_pnl": Decimal("99.0"),
                }
            ],
            closed_positions=[],
            market_statuses={"0xmarket": {"status": "open"}},
        ),
        run_id="run-1",
        calculated_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    market_result = result.wallet_market_results[0]
    assert market_result["realized_pnl"] == Decimal("0")
    assert market_result["unrealized_pnl"] == Decimal("3.0")
    assert market_result["current_value"] == Decimal("7.0")
    assert market_result["net_pnl"] == Decimal("3.0")
    assert market_result["result_status"] == "open"


def test_pnl_uses_closed_positions_for_realized_pnl_and_reconciliation() -> None:
    result = calculate_wallet_pnl(
        PnLInput(
            wallet_address="0xabc",
            trades=[
                {
                    "condition_id": "0xmarket",
                    "token_id": "111",
                    "outcome": "Yes",
                    "side": "BUY",
                    "price": Decimal("0.40"),
                    "size": Decimal("10"),
                    "notional": Decimal("4.0"),
                    "trade_timestamp": datetime(2026, 7, 1, tzinfo=UTC),
                    "raw": {},
                },
                {
                    "condition_id": "0xmarket",
                    "token_id": "111",
                    "outcome": "Yes",
                    "side": "SELL",
                    "price": Decimal("0.70"),
                    "size": Decimal("10"),
                    "notional": Decimal("7.0"),
                    "trade_timestamp": datetime(2026, 7, 5, tzinfo=UTC),
                    "raw": {},
                },
            ],
            closed_positions=[
                {
                    "condition_id": "0xmarket",
                    "token_id": "111",
                    "outcome": "Yes",
                    "realized_pnl": Decimal("3.0"),
                    "cur_price": Decimal("1"),
                    "closed_at": datetime(2026, 7, 6, tzinfo=UTC),
                }
            ],
            market_statuses={"0xmarket": {"status": "closed"}},
        ),
        run_id="run-1",
        calculated_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    market_result = result.wallet_market_results[0]
    assert market_result["realized_pnl"] == Decimal("3.0")
    assert market_result["unrealized_pnl"] == Decimal("0")
    assert market_result["outcome_correct"] is True
    assert market_result["result_status"] == "settled"
    assert market_result["avg_buy_price"] == Decimal("0.40")
    assert market_result["avg_sell_price"] == Decimal("0.70")
    assert result.reconciliation_checks[0]["status"] == "matched"


def test_wallet_profile_summary_calculates_profit_factor_and_concentration() -> None:
    profile = summarize_wallet_profile(
        [
            {
                "result_status": "settled",
                "realized_pnl": Decimal("6"),
                "unrealized_pnl": Decimal("0"),
                "net_pnl": Decimal("6"),
                "capital_deployed": Decimal("20"),
            },
            {
                "result_status": "settled",
                "realized_pnl": Decimal("-2"),
                "unrealized_pnl": Decimal("0"),
                "net_pnl": Decimal("-2"),
                "capital_deployed": Decimal("10"),
            },
        ]
    )

    assert profile["realized_pnl"] == Decimal("4")
    assert profile["net_roi"] == Decimal("0.1333333333333333333333333333")
    assert profile["profit_factor"] == Decimal("3")
    assert profile["win_rate"] == Decimal("0.5")
    assert profile["single_market_profit_share"] == Decimal("1")
