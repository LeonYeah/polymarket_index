from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from backend.app.analytics.paper_trading import (
    BookLevel,
    MarketContext,
    Signal,
    StrategyConfig,
    calculate_paper_pnl,
    calculate_wallet_weight,
    merge_aligned_signals,
    simulate_order,
)

NOW = datetime(2026, 7, 10, 12, tzinfo=UTC)


def signal(**overrides: object) -> Signal:
    values = {
        "signal_id": "signal-1",
        "source_trade_uid": "trade-1",
        "leader_wallet": "0xleader",
        "market_id": "condition-1",
        "token_id": "token-1",
        "side": "BUY",
        "leader_price": Decimal("0.50"),
        "leader_size": Decimal("100"),
        "leader_trade_time": NOW - timedelta(seconds=5),
        "detected_at": NOW - timedelta(seconds=2),
        "score": Decimal("80"),
        "confidence": Decimal("0.8"),
        "wallet_weight": Decimal("0.75"),
        "reason": "high_score_wallet_trade",
        "evidence": {"expected_edge": Decimal("0.02")},
    }
    values.update(overrides)
    return Signal(**values)  # type: ignore[arg-type]


def market(**overrides: object) -> MarketContext:
    values = {
        "accepting_orders": True,
        "end_date": NOW + timedelta(days=3),
        "snapshot_at": NOW - timedelta(seconds=1),
        "liquidity_score": Decimal("85"),
        "spread_bps": Decimal("100"),
        "midpoint": Decimal("0.50"),
        "snapshot_uid": "book-1",
    }
    values.update(overrides)
    return MarketContext(**values)  # type: ignore[arg-type]


def test_wallet_weight_uses_all_four_bounded_components() -> None:
    assert calculate_wallet_weight(
        score=80,
        category_expertise=Decimal("0.5"),
        recent_stability=Decimal("0.75"),
        followability=90,
    ) == Decimal("0.7500")


def test_aligned_signals_merge_and_keep_child_traceability() -> None:
    second = signal(
        signal_id="signal-2",
        source_trade_uid="trade-2",
        leader_wallet="0xother",
        leader_price=Decimal("0.55"),
        wallet_weight=Decimal("0.25"),
    )
    merged = merge_aligned_signals([signal(), second])
    assert merged.reason == "aligned_wallet_signals_merged"
    assert merged.merged_signal_ids == ("signal-1", "signal-2")
    assert merged.leader_price == Decimal("0.5125")
    assert merged.wallet_weight == Decimal("1.00")


def test_merge_rejects_opposite_direction() -> None:
    with pytest.raises(ValueError, match="aligned"):
        merge_aligned_signals([signal(), signal(signal_id="signal-2", side="SELL")])


def test_fak_walks_book_and_records_partial_fill_and_latency() -> None:
    order = simulate_order(
        signal(),
        market(),
        [BookLevel(Decimal("0.51"), Decimal("40")), BookLevel(Decimal("0.52"), Decimal("20"))],
        order_type="FAK",
        decision_at=NOW,
        simulated_at=NOW + timedelta(milliseconds=25),
    )
    assert order.status == "would_partial_fill"
    assert order.filled_size == Decimal("60")
    assert order.estimated_fill_price == Decimal("0.5133333333333333333333333333")
    assert order.detection_latency_ms == 3000
    assert order.decision_latency_ms == 2000
    assert order.simulation_latency_ms == 25


def test_fok_rejects_partial_liquidity() -> None:
    order = simulate_order(
        signal(),
        market(),
        [BookLevel(Decimal("0.51"), Decimal("20"))],
        order_type="FOK",
        decision_at=NOW,
    )
    assert order.status == "rejected"
    assert order.reject_reason == "low_liquidity"
    assert order.filled_size == 0


def test_gtc_stays_created_when_nothing_is_immediately_fillable() -> None:
    order = simulate_order(signal(), market(), [], order_type="GTC", decision_at=NOW)
    assert order.status == "created"
    assert order.reject_reason is None


@pytest.mark.parametrize(
    ("signal_override", "market_override", "reason"),
    [
        ({"score": Decimal("20")}, {}, "insufficient_score"),
        ({"confidence": Decimal("0.1")}, {}, "low_confidence"),
        ({}, {"accepting_orders": False}, "market_not_accepting_orders"),
        ({}, {"snapshot_at": NOW - timedelta(minutes=5)}, "stale_data"),
        ({"detected_at": NOW - timedelta(minutes=20)}, {}, "late_signal"),
        ({}, {"liquidity_score": Decimal("10")}, "low_liquidity"),
        ({}, {"spread_bps": Decimal("900")}, "wide_spread"),
        ({"evidence": {"expected_edge": Decimal("-0.01")}}, {}, "negative_expected_edge"),
        ({}, {"compliance_blocked": True}, "compliance_block"),
    ],
)
def test_every_risk_gate_has_an_explicit_reject_reason(
    signal_override: dict[str, object],
    market_override: dict[str, object],
    reason: str,
) -> None:
    order = simulate_order(
        signal(**signal_override),
        market(**market_override),
        [BookLevel(Decimal("0.50"), Decimal("1000"))],
        config=StrategyConfig(),
        decision_at=NOW,
    )
    assert order.status == "rejected"
    assert order.reject_reason == reason


def test_watchlist_signal_can_bypass_score_but_not_confidence_gate() -> None:
    order = simulate_order(
        signal(score=Decimal("0"), reason="watchlist_wallet_trade"),
        market(),
        [BookLevel(Decimal("0.50"), Decimal("1000"))],
        decision_at=NOW,
    )
    assert order.status == "would_fill"


def test_pnl_distinguishes_correct_direction_from_profit_after_costs() -> None:
    result = calculate_paper_pnl(
        side="BUY",
        entry_price="0.55",
        exit_price="0.56",
        filled_size="10",
        fee="0.20",
        leader_price="0.50",
    )
    assert result.direction_correct is True
    assert result.gross_pnl == Decimal("0.10")
    assert result.net_pnl == Decimal("-0.10")
    assert result.profitable_after_costs is False


def test_token_exposure_limit_rejects_new_order_at_configured_cap() -> None:
    order = simulate_order(
        signal(reason="watchlist_wallet_trade"),
        market(),
        [BookLevel(Decimal("0.50"), Decimal("1000"))],
        config=StrategyConfig(maximum_token_notional=Decimal("100")),
        current_token_exposure=Decimal("100"),
        decision_at=NOW,
    )

    assert order.status == "rejected"
    assert order.reject_reason == "token_exposure_limit"
    assert order.requested_notional == 0
    assert order.filled_size == 0


def test_token_exposure_limit_uses_only_remaining_cost_basis() -> None:
    order = simulate_order(
        signal(reason="watchlist_wallet_trade"),
        market(),
        [BookLevel(Decimal("0.51"), Decimal("1000"))],
        config=StrategyConfig(maximum_token_notional=Decimal("100")),
        current_token_exposure=Decimal("90"),
        decision_at=NOW,
    )

    assert order.status == "would_partial_fill"
    assert order.requested_notional == Decimal("10")
    assert order.filled_size * order.estimated_fill_price == Decimal("10")
    assert order.evidence["remaining_token_notional"] == Decimal("10")
