from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.analytics.smart_score import (
    calculate_bayesian_win_rate,
    score_wallet_features,
    select_backtest_strategies,
    summarize_backtest_results,
)


def _features(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "wallet_address": "0xabc",
        "feature_uid": "feature-1",
        "n_resolved": 60,
        "active_days_180d": 45,
        "realized_notional_180d": Decimal("30000"),
        "realized_pnl_180d": Decimal("4500"),
        "open_unrealized_pnl": Decimal("0"),
        "capital_deployed_180d": Decimal("30000"),
        "net_roi_180d": Decimal("0.15"),
        "gross_profit_180d": Decimal("8000"),
        "gross_loss_180d": Decimal("3500"),
        "profit_factor": Decimal("2.2857"),
        "win_rate": Decimal("0.62"),
        "bayes_wr": Decimal("0.60"),
        "max_drawdown_ratio": Decimal("0.12"),
        "single_market_pnl_share": Decimal("0.22"),
        "avg_clv_30s": Decimal("0.01"),
        "avg_clv_2m": Decimal("0.02"),
        "avg_clv_10m": Decimal("0.03"),
        "avg_clv_1h": Decimal("0.04"),
        "avg_clv_24h": Decimal("0.05"),
        "positive_clv_share": Decimal("0.64"),
        "clv_sample_count": 80,
        "avg_followability": Decimal("72"),
        "low_liquidity_trade_share": Decimal("0.20"),
    }
    base.update(overrides)
    return base


def test_bayesian_win_rate_uses_neutral_prior() -> None:
    assert calculate_bayesian_win_rate(0, 0) == Decimal("0.55")
    assert calculate_bayesian_win_rate(60, 40) > Decimal("0.55")


def test_smart_score_marks_high_confidence_wallet_eligible() -> None:
    result = score_wallet_features(
        _features(),
        scored_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result.high_confidence_eligible is True
    assert result.score > Decimal("40")
    assert result.confidence >= Decimal("0.70")
    assert result.exclusion_reasons == []


def test_small_sample_high_roi_wallet_is_score_capped_and_excluded() -> None:
    result = score_wallet_features(
        _features(
            n_resolved=5,
            active_days_180d=5,
            realized_notional_180d=Decimal("1000"),
            realized_pnl_180d=Decimal("700"),
            net_roi_180d=Decimal("0.70"),
            bayes_wr=Decimal("0.80"),
        ),
        scored_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result.high_confidence_eligible is False
    assert result.score <= Decimal("60")
    assert "n_resolved_gte_50" in result.exclusion_reasons


def test_single_market_windfall_is_penalized() -> None:
    result = score_wallet_features(
        _features(single_market_pnl_share=Decimal("0.80")),
        scored_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result.high_confidence_eligible is False
    assert any(row["reason"] == "single_market_profit_concentration" for row in result.penalty_summary)
    assert "single_market_pnl_share_lte_30pct" in result.exclusion_reasons


def test_positive_clv_losing_wallet_keeps_prediction_quality_signal() -> None:
    result = score_wallet_features(
        _features(
            realized_pnl_180d=Decimal("-500"),
            net_roi_180d=Decimal("-0.03"),
            avg_clv_10m=Decimal("0.06"),
            positive_clv_share=Decimal("0.75"),
        ),
        scored_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result.component_summary["prediction_quality"] > result.component_summary["return_quality"]
    assert "net_roi_180d_gte_8pct" in result.exclusion_reasons


def test_backtest_strategy_selection_covers_three_strategy_classes() -> None:
    rows = [
        {
            "wallet_address": "0x1",
            "score": Decimal("80"),
            "confidence": Decimal("0.9"),
            "realized_pnl_180d": Decimal("100"),
            "net_roi_180d": Decimal("0.10"),
            "active_days_180d": 10,
        },
        {
            "wallet_address": "0x2",
            "score": Decimal("50"),
            "confidence": Decimal("0.8"),
            "realized_pnl_180d": Decimal("1000"),
            "net_roi_180d": Decimal("0.20"),
            "active_days_180d": 12,
        },
    ]

    selections = select_backtest_strategies(rows, top_n=1)
    assert {row.strategy for row in selections} == {"top_score", "top_pnl", "random_active"}
    assert next(row for row in selections if row.strategy == "top_score").wallet_address == "0x1"
    assert next(row for row in selections if row.strategy == "top_pnl").wallet_address == "0x2"


def test_backtest_summary_groups_future_performance_by_strategy() -> None:
    summary = summarize_backtest_results(
        [
            {
                "strategy": "top_score",
                "training_score": Decimal("80"),
                "future_net_pnl": Decimal("10"),
                "future_capital_deployed": Decimal("100"),
                "future_avg_clv_10m": Decimal("0.02"),
            },
            {
                "strategy": "top_score",
                "training_score": Decimal("70"),
                "future_net_pnl": Decimal("-2"),
                "future_capital_deployed": Decimal("50"),
                "future_avg_clv_10m": Decimal("0.01"),
            },
        ]
    )

    assert summary["top_score"]["wallets"] == 2
    assert summary["top_score"]["future_net_pnl"] == Decimal("8")
    assert summary["top_score"]["future_roi"] == Decimal("0.05333333333333333333333333333")
