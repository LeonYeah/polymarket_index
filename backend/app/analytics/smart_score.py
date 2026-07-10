from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
SMART_SCORE_VERSION = "smart_score_v2"
FEATURE_VERSION = "wallet_features_v1"

WEIGHT_CONFIG: dict[str, Decimal] = {
    "return_quality": Decimal("25"),
    "prediction_quality": Decimal("25"),
    "timing_advantage": Decimal("20"),
    "stability": Decimal("15"),
    "followability": Decimal("10"),
    "network_signal": Decimal("5"),
}


@dataclass(frozen=True)
class SmartScoreResult:
    wallet_address: str
    score_uid: str
    feature_uid: str
    score_version: str
    score: Decimal
    raw_score: Decimal
    confidence: Decimal
    high_confidence_eligible: bool
    hard_gate_status: dict[str, bool]
    exclusion_reasons: list[str]
    penalty_summary: list[dict[str, Any]]
    component_summary: dict[str, Decimal]
    components: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class StrategySelection:
    strategy: str
    wallet_address: str
    strategy_rank: int
    training_score: Decimal | None
    training_confidence: Decimal | None
    training_features: dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return default


def stable_uid(parts: Iterable[Any]) -> str:
    payload = json.dumps(list(parts), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def calculate_bayesian_win_rate(wins: int, losses: int, *, alpha: Decimal = Decimal("11"), beta: Decimal = Decimal("9")) -> Decimal:
    return (Decimal(wins) + alpha) / (Decimal(wins + losses) + alpha + beta)


def build_feature_uid(wallet_address: str, feature_version: str, as_of: datetime) -> str:
    return stable_uid(["wallet_features", wallet_address, feature_version, as_of])


def build_score_uid(wallet_address: str, score_version: str, scored_at: datetime) -> str:
    return stable_uid(["wallet_score", wallet_address, score_version, scored_at])


def score_wallet_features(
    features: Mapping[str, Any],
    *,
    scored_at: datetime | None = None,
    score_version: str = SMART_SCORE_VERSION,
) -> SmartScoreResult:
    scored_at = scored_at or utc_now()
    wallet_address = str(features["wallet_address"])
    feature_uid = str(features["feature_uid"])
    components = [
        _return_quality(features),
        _prediction_quality(features),
        _timing_advantage(features),
        _stability(features),
        _followability(features),
        _network_signal(),
    ]
    raw_score = _quantize(sum((as_decimal(row["component_score"]) for row in components), ZERO))
    hard_gate_status = _hard_gate_status(features)
    exclusion_reasons = [name for name, passed in hard_gate_status.items() if not passed]
    penalties, cap = _penalties(features)
    penalized_score = raw_score - sum((as_decimal(row["points"]) for row in penalties), ZERO)
    if cap is not None and penalized_score > cap:
        penalties.append({"reason": "small_sample_score_cap", "points": penalized_score - cap, "cap": cap})
        penalized_score = cap
    score = _clamp(penalized_score, ZERO, HUNDRED)
    confidence = _confidence(features)
    return SmartScoreResult(
        wallet_address=wallet_address,
        score_uid=build_score_uid(wallet_address, score_version, scored_at),
        feature_uid=feature_uid,
        score_version=score_version,
        score=_quantize(score),
        raw_score=raw_score,
        confidence=confidence,
        high_confidence_eligible=all(hard_gate_status.values()),
        hard_gate_status=hard_gate_status,
        exclusion_reasons=exclusion_reasons,
        penalty_summary=penalties,
        component_summary={str(row["component_name"]): as_decimal(row["component_score"]) for row in components},
        components=components,
    )


def select_backtest_strategies(
    score_rows: Iterable[Mapping[str, Any]],
    *,
    top_n: int = 10,
) -> list[StrategySelection]:
    rows = [dict(row) for row in score_rows]
    selections: list[StrategySelection] = []
    selections.extend(_select_ranked(rows, strategy="top_score", key=lambda row: (as_decimal(row.get("score")), as_decimal(row.get("confidence"))), top_n=top_n))
    selections.extend(_select_ranked(rows, strategy="top_pnl", key=lambda row: (as_decimal(row.get("realized_pnl_180d")), as_decimal(row.get("net_roi_180d"))), top_n=top_n))
    active_rows = [row for row in rows if as_decimal(row.get("active_days_180d")) > ZERO]
    random_like = sorted(active_rows, key=lambda row: stable_uid(["random_active", row.get("wallet_address")]))
    selections.extend(_selection_from_rows(random_like[:top_n], "random_active"))
    return selections


def summarize_backtest_results(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["strategy"]), []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for strategy, strategy_rows in grouped.items():
        total_pnl = sum((as_decimal(row.get("future_net_pnl")) for row in strategy_rows), ZERO)
        total_capital = sum((as_decimal(row.get("future_capital_deployed")) for row in strategy_rows), ZERO)
        avg_score = _avg(as_decimal(row.get("training_score")) for row in strategy_rows if row.get("training_score") is not None)
        summary[strategy] = {
            "wallets": len(strategy_rows),
            "future_net_pnl": total_pnl,
            "future_capital_deployed": total_capital,
            "future_roi": _safe_divide(total_pnl, total_capital),
            "avg_training_score": avg_score,
            "avg_future_clv_10m": _avg(
                as_decimal(row.get("future_avg_clv_10m"))
                for row in strategy_rows
                if row.get("future_avg_clv_10m") is not None
            ),
        }
    return summary


def _return_quality(features: Mapping[str, Any]) -> dict[str, Any]:
    realized_pnl = as_decimal(features.get("realized_pnl_180d"))
    net_roi = as_decimal(features.get("net_roi_180d"))
    profit_factor = as_decimal(features.get("profit_factor"))
    return _component(
        "return_quality",
        Decimal("25"),
        {
            "realized_pnl": _scale(realized_pnl, Decimal("25000")) * Decimal("8"),
            "net_roi": _scale(net_roi, Decimal("0.30")) * Decimal("8"),
            "profit_factor": _scale(profit_factor - ONE, Decimal("3")) * Decimal("5"),
            "positive_after_cost_proxy": _scale(net_roi, Decimal("0.12")) * Decimal("4"),
        },
    )


def _prediction_quality(features: Mapping[str, Any]) -> dict[str, Any]:
    bayes_wr = as_decimal(features.get("bayes_wr"))
    avg_clv = _first_decimal(features, ["avg_clv_10m", "avg_clv_2m", "avg_clv_30s"])
    positive_clv_share = as_decimal(features.get("positive_clv_share"))
    return _component(
        "prediction_quality",
        Decimal("25"),
        {
            "bayesian_win_rate": _scale(bayes_wr - Decimal("0.50"), Decimal("0.25")) * Decimal("10"),
            "average_clv": _scale(avg_clv, Decimal("0.08")) * Decimal("10"),
            "positive_clv_share": _scale(positive_clv_share - Decimal("0.50"), Decimal("0.35")) * Decimal("5"),
        },
    )


def _timing_advantage(features: Mapping[str, Any]) -> dict[str, Any]:
    clv_30s = as_decimal(features.get("avg_clv_30s"))
    clv_2m = as_decimal(features.get("avg_clv_2m"))
    clv_10m = as_decimal(features.get("avg_clv_10m"))
    return _component(
        "timing_advantage",
        Decimal("20"),
        {
            "early_price_move_30s": _scale(clv_30s, Decimal("0.04")) * Decimal("8"),
            "price_move_2m": _scale(clv_2m, Decimal("0.06")) * Decimal("6"),
            "price_move_10m": _scale(clv_10m, Decimal("0.08")) * Decimal("6"),
        },
    )


def _stability(features: Mapping[str, Any]) -> dict[str, Any]:
    active_days = as_decimal(features.get("active_days_180d"))
    max_dd_ratio = as_decimal(features.get("max_drawdown_ratio"))
    concentration = as_decimal(features.get("single_market_pnl_share"))
    return _component(
        "stability",
        Decimal("15"),
        {
            "active_days": _scale(active_days, Decimal("60")) * Decimal("5"),
            "drawdown_control": (ONE - _scale(max_dd_ratio, Decimal("0.30"))) * Decimal("6"),
            "pnl_concentration": (ONE - _scale(concentration, Decimal("0.50"))) * Decimal("4"),
        },
    )


def _followability(features: Mapping[str, Any]) -> dict[str, Any]:
    avg_followability = as_decimal(features.get("avg_followability"))
    low_liquidity_share = as_decimal(features.get("low_liquidity_trade_share"))
    return _component(
        "followability",
        Decimal("10"),
        {
            "market_liquidity_score": _scale(avg_followability, HUNDRED) * Decimal("8"),
            "low_liquidity_penalty": (ONE - _scale(low_liquidity_share, ONE)) * Decimal("2"),
        },
    )


def _network_signal() -> dict[str, Any]:
    return _component("network_signal", Decimal("5"), {"neutral_placeholder": Decimal("2.5")})


def _component(name: str, max_score: Decimal, details: Mapping[str, Decimal]) -> dict[str, Any]:
    score = _clamp(sum(details.values(), ZERO), ZERO, max_score)
    return {
        "component_name": name,
        "component_score": _quantize(score),
        "max_score": max_score,
        "details": {key: _quantize(value) for key, value in details.items()},
    }


def _hard_gate_status(features: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "n_resolved_gte_50": as_decimal(features.get("n_resolved")) >= Decimal("50"),
        "active_days_180d_gte_30": as_decimal(features.get("active_days_180d")) >= Decimal("30"),
        "realized_notional_180d_gte_25000": as_decimal(features.get("realized_notional_180d")) >= Decimal("25000"),
        "net_roi_180d_gte_8pct": as_decimal(features.get("net_roi_180d")) >= Decimal("0.08"),
        "bayes_wr_gte_55pct": as_decimal(features.get("bayes_wr")) >= Decimal("0.55"),
        "max_dd_lte_20pct": as_decimal(features.get("max_drawdown_ratio")) <= Decimal("0.20"),
        "followability_gte_60": as_decimal(features.get("avg_followability")) >= Decimal("60"),
    }


def _penalties(features: Mapping[str, Any]) -> tuple[list[dict[str, Any]], Decimal | None]:
    penalties: list[dict[str, Any]] = []
    cap: Decimal | None = None
    n_resolved = as_decimal(features.get("n_resolved"))
    concentration = as_decimal(features.get("single_market_pnl_share"))
    low_liquidity_share = as_decimal(features.get("low_liquidity_trade_share"))
    if n_resolved < Decimal("20"):
        cap = Decimal("60")
    elif n_resolved < Decimal("50"):
        cap = Decimal("75")
    if concentration > Decimal("0.50"):
        points = Decimal("10") + _scale(concentration - Decimal("0.50"), Decimal("0.50")) * Decimal("15")
        penalties.append({"reason": "single_market_profit_concentration", "points": _quantize(points), "share": concentration})
    if low_liquidity_share > Decimal("0.50"):
        points = _scale(low_liquidity_share - Decimal("0.50"), Decimal("0.50")) * Decimal("10")
        penalties.append({"reason": "low_liquidity_market_share", "points": _quantize(points), "share": low_liquidity_share})
    return penalties, cap


def _confidence(features: Mapping[str, Any]) -> Decimal:
    n_resolved_factor = _scale(as_decimal(features.get("n_resolved")), Decimal("80"))
    active_factor = _scale(as_decimal(features.get("active_days_180d")), Decimal("60"))
    follow_factor = _scale(as_decimal(features.get("avg_followability")), HUNDRED)
    clv_factor = _scale(as_decimal(features.get("clv_sample_count")), Decimal("100"))
    unrealized_ratio = _safe_divide(
        abs(as_decimal(features.get("open_unrealized_pnl"))),
        abs(as_decimal(features.get("realized_pnl_180d"))) + abs(as_decimal(features.get("open_unrealized_pnl"))),
    ) or ZERO
    confidence = (n_resolved_factor * Decimal("0.35")) + (active_factor * Decimal("0.20"))
    confidence += follow_factor * Decimal("0.20") + clv_factor * Decimal("0.15") + Decimal("0.10")
    confidence -= _scale(unrealized_ratio - Decimal("0.50"), Decimal("0.50")) * Decimal("0.20")
    return _quantize(_clamp(confidence, ZERO, ONE))


def _select_ranked(
    rows: list[dict[str, Any]],
    *,
    strategy: str,
    key: Any,
    top_n: int,
) -> list[StrategySelection]:
    ranked = sorted(rows, key=key, reverse=True)
    return _selection_from_rows(ranked[:top_n], strategy)


def _selection_from_rows(rows: list[dict[str, Any]], strategy: str) -> list[StrategySelection]:
    return [
        StrategySelection(
            strategy=strategy,
            wallet_address=str(row["wallet_address"]),
            strategy_rank=index,
            training_score=as_decimal(row.get("score")) if row.get("score") is not None else None,
            training_confidence=as_decimal(row.get("confidence")) if row.get("confidence") is not None else None,
            training_features=dict(row.get("feature_snapshot") or row),
        )
        for index, row in enumerate(rows, start=1)
    ]


def _first_decimal(features: Mapping[str, Any], names: list[str]) -> Decimal:
    for name in names:
        if features.get(name) is not None:
            return as_decimal(features.get(name))
    return ZERO


def _avg(values: Iterable[Decimal]) -> Decimal | None:
    rows = list(values)
    if not rows:
        return None
    return sum(rows, ZERO) / Decimal(len(rows))


def _safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == ZERO:
        return None
    return numerator / denominator


def _scale(value: Decimal, full_scale: Decimal) -> Decimal:
    if full_scale <= ZERO:
        return ZERO
    return _clamp(value / full_scale, ZERO, ONE)


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"))
