from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.collectors.wallet_data import (
    normalize_active_trader_candidates,
    normalize_closed_position,
    normalize_current_position,
    normalize_leaderboard_candidates,
    normalize_trade,
)


def test_normalize_leaderboard_candidates_records_period_source() -> None:
    wallets, candidates = normalize_leaderboard_candidates(
        [
            {
                "rank": "1",
                "proxyWallet": "0xABC",
                "pnl": "12.5",
                "vol": "99",
            }
        ],
        period="DAY",
        run_id="run-1",
        discovered_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert wallets[0]["wallet_address"] == "0xabc"
    assert candidates[0]["seed_source"] == "leaderboard"
    assert candidates[0]["seed_ref"] == "DAY"
    assert candidates[0]["score"] == Decimal("12.5")


def test_normalize_active_trader_candidates_dedupes_wallets() -> None:
    _, candidates = normalize_active_trader_candidates(
        [
            {"proxyWallet": "0xABC", "price": "0.5", "size": "10", "conditionId": "0xmarket"},
            {"proxyWallet": "0xabc", "price": "0.7", "size": "20", "conditionId": "0xmarket"},
        ],
        run_id="run-1",
        discovered_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert len(candidates) == 1
    assert candidates[0]["wallet_address"] == "0xabc"
    assert candidates[0]["score"] == Decimal("5.0")


def test_normalize_trade_generates_stable_uid_and_notional() -> None:
    raw = {
        "proxyWallet": "0xABC",
        "side": "BUY",
        "asset": "111",
        "conditionId": "0xmarket",
        "size": "10",
        "price": "0.42",
        "timestamp": 1710000000000,
        "transactionHash": "0xtx",
    }

    first = normalize_trade(raw, wallet_address=None, run_id="run-1", taker_only=False)
    second = normalize_trade(raw, wallet_address=None, run_id="run-2", taker_only=False)

    assert first is not None
    assert second is not None
    assert first["trade_uid"] == second["trade_uid"]
    assert first["wallet_address"] == "0xabc"
    assert first["notional"] == Decimal("4.20")
    assert first["trade_timestamp"] == datetime.fromtimestamp(1710000000, UTC)


def test_current_position_keeps_unrealized_values_separate_from_realized_pnl() -> None:
    position = normalize_current_position(
        {
            "proxyWallet": "0xABC",
            "asset": "111",
            "conditionId": "0xmarket",
            "size": "2",
            "avgPrice": "0.25",
            "currentValue": "0.8",
            "cashPnl": "0.3",
            "realizedPnl": "0",
            "outcome": "Yes",
        },
        wallet_address="0xabc",
        run_id="run-1",
        snapshot_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert position is not None
    assert position["current_value"] == Decimal("0.8")
    assert position["cash_pnl"] == Decimal("0.3")
    assert position["realized_pnl"] == Decimal("0")


def test_closed_position_uses_realized_pnl_and_closed_timestamp() -> None:
    position = normalize_closed_position(
        {
            "proxyWallet": "0xABC",
            "asset": "111",
            "conditionId": "0xmarket",
            "avgPrice": "0.4",
            "totalBought": "20",
            "realizedPnl": "3.5",
            "timestamp": 1710000000,
        },
        wallet_address="0xabc",
        run_id="run-1",
    )

    assert position is not None
    assert position["wallet_address"] == "0xabc"
    assert position["realized_pnl"] == Decimal("3.5")
    assert position["closed_at"] == datetime.fromtimestamp(1710000000, UTC)
