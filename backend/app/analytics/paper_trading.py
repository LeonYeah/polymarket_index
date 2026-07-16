from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

ZERO = Decimal("0")
ONE = Decimal("1")
PAPER_STRATEGY_VERSION = "weighted_copy_v1"
SIGNAL_ENGINE_VERSION = "signal_engine_v1"

Side = Literal["BUY", "SELL"]
OrderType = Literal["FOK", "FAK", "GTC"]


def as_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def stable_uid(parts: Iterable[Any]) -> str:
    payload = json.dumps(list(parts), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class StrategyConfig:
    strategy_version: str = PAPER_STRATEGY_VERSION
    minimum_score: Decimal = Decimal("60")
    minimum_confidence: Decimal = Decimal("0.35")
    minimum_liquidity_score: Decimal = Decimal("40")
    maximum_spread_bps: Decimal = Decimal("500")
    maximum_book_age: timedelta = timedelta(minutes=2)
    maximum_signal_age: timedelta = timedelta(minutes=10)
    settlement_buffer: timedelta = timedelta(hours=1)
    fee_rate: Decimal = Decimal("0.002")
    maximum_notional: Decimal = Decimal("100")
    maximum_token_notional: Decimal = Decimal("100")
    minimum_notional: Decimal = Decimal("5")
    default_worst_price_move: Decimal = Decimal("0.03")


@dataclass(frozen=True)
class Signal:
    signal_id: str
    source_trade_uid: str | None
    leader_wallet: str
    market_id: str
    token_id: str
    side: Side
    leader_price: Decimal
    leader_size: Decimal
    leader_trade_time: datetime
    detected_at: datetime
    score: Decimal
    confidence: Decimal
    wallet_weight: Decimal
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    merged_signal_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketContext:
    accepting_orders: bool
    end_date: datetime | None
    snapshot_at: datetime | None
    liquidity_score: Decimal
    spread_bps: Decimal | None
    midpoint: Decimal | None
    snapshot_uid: str | None = None
    compliance_blocked: bool = False
    metadata_available: bool = True


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class PaperOrderDecision:
    order_id: str
    signal_id: str
    strategy_version: str
    order_type: OrderType
    side: Side
    market_id: str
    token_id: str
    requested_size: Decimal
    requested_notional: Decimal
    worst_price: Decimal
    estimated_fill_price: Decimal | None
    filled_size: Decimal
    estimated_slippage: Decimal
    estimated_fee: Decimal
    status: str
    reject_reason: str | None
    leader_trade_time: datetime
    signal_detected_at: datetime
    decision_at: datetime
    order_simulated_at: datetime
    detection_latency_ms: int
    decision_latency_ms: int
    simulation_latency_ms: int
    orderbook_snapshot_uid: str | None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperPnl:
    gross_pnl: Decimal
    fee: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal
    direction_correct: bool
    profitable_after_costs: bool


def calculate_wallet_weight(
    *,
    score: Any,
    category_expertise: Any,
    recent_stability: Any,
    followability: Any,
) -> Decimal:
    """Return the v1 copy weight, with every component normalized to [0, 1]."""
    normalized = (
        _unit(as_decimal(score) / Decimal("100")) * Decimal("0.40")
        + _unit(as_decimal(category_expertise)) * Decimal("0.20")
        + _unit(as_decimal(recent_stability)) * Decimal("0.20")
        + _unit(as_decimal(followability) / Decimal("100")) * Decimal("0.20")
    )
    return normalized.quantize(Decimal("0.0001"))


def build_signal(row: Mapping[str, Any], *, detected_at: datetime | None = None) -> Signal:
    detected_at = detected_at or utc_now()
    score = as_decimal(row.get("score"))
    confidence = as_decimal(row.get("confidence"))
    reason = "watchlist_wallet_trade" if row.get("watchlisted") else "high_score_wallet_trade"
    weight = calculate_wallet_weight(
        score=score,
        category_expertise=row.get("category_expertise", confidence),
        recent_stability=row.get("recent_stability", confidence),
        followability=row.get("followability"),
    )
    source_trade_uid = str(row["trade_uid"]) if row.get("trade_uid") else None
    wallet = str(row["wallet_address"])
    signal_id = stable_uid([SIGNAL_ENGINE_VERSION, source_trade_uid, wallet])
    return Signal(
        signal_id=signal_id,
        source_trade_uid=source_trade_uid,
        leader_wallet=wallet,
        market_id=str(row["condition_id"]),
        token_id=str(row["token_id"]),
        side=str(row["side"]).upper(),  # type: ignore[arg-type]
        leader_price=as_decimal(row.get("price")),
        leader_size=as_decimal(row.get("size")),
        leader_trade_time=row["trade_timestamp"],
        detected_at=detected_at,
        score=score,
        confidence=confidence,
        wallet_weight=weight,
        reason=reason,
        evidence={
            "score": score,
            "high_confidence_eligible": bool(row.get("high_confidence_eligible")),
            "watchlisted": bool(row.get("watchlisted")),
            "category_expertise": row.get("category_expertise"),
            "recent_stability": row.get("recent_stability"),
            "followability": row.get("followability"),
            "expected_edge": row.get("expected_edge"),
            "n_resolved": row.get("n_resolved"),
        },
    )


def merge_aligned_signals(signals: Sequence[Signal]) -> Signal:
    """Merge same-token/same-side signals while preserving child traceability."""
    if not signals:
        raise ValueError("at least one signal is required")
    first = signals[0]
    if any(
        (row.market_id, row.token_id, row.side) != (first.market_id, first.token_id, first.side)
        for row in signals
    ):
        raise ValueError("only aligned market, token, and side signals can be merged")
    if len(signals) == 1:
        return first
    total_weight = sum((row.wallet_weight for row in signals), ZERO)
    denominator = total_weight or Decimal(len(signals))
    weighted_price = (
        sum((row.leader_price * row.wallet_weight for row in signals), ZERO) / denominator
        if total_weight > ZERO
        else sum((row.leader_price for row in signals), ZERO) / denominator
    )
    merged_ids = tuple(sorted(row.signal_id for row in signals))
    detected_at = max(row.detected_at for row in signals)
    return Signal(
        signal_id=stable_uid([SIGNAL_ENGINE_VERSION, "merged", *merged_ids]),
        source_trade_uid=None,
        leader_wallet=first.leader_wallet,
        market_id=first.market_id,
        token_id=first.token_id,
        side=first.side,
        leader_price=weighted_price,
        leader_size=sum((row.leader_size for row in signals), ZERO),
        leader_trade_time=min(row.leader_trade_time for row in signals),
        detected_at=detected_at,
        score=max(row.score for row in signals),
        confidence=sum((row.confidence for row in signals), ZERO) / Decimal(len(signals)),
        wallet_weight=min(ONE, total_weight),
        reason="aligned_wallet_signals_merged",
        evidence={"leader_wallets": sorted({row.leader_wallet for row in signals})},
        merged_signal_ids=merged_ids,
    )


def simulate_order(
    signal: Signal,
    market: MarketContext,
    levels: Sequence[BookLevel],
    *,
    order_type: OrderType = "FAK",
    config: StrategyConfig | None = None,
    current_token_exposure: Decimal = ZERO,
    decision_at: datetime | None = None,
    simulated_at: datetime | None = None,
) -> PaperOrderDecision:
    config = config or StrategyConfig()
    decision_at = decision_at or utc_now()
    simulated_at = simulated_at or decision_at
    reference_price = market.midpoint or signal.leader_price
    remaining_token_notional = max(
        ZERO,
        config.maximum_token_notional - max(ZERO, current_token_exposure),
    )
    desired_notional = min(
        config.maximum_notional,
        max(
            config.minimum_notional, signal.leader_price * signal.leader_size * signal.wallet_weight
        ),
    )
    target_notional = min(desired_notional, remaining_token_notional)
    requested_size = target_notional / reference_price if reference_price > ZERO else ZERO
    price_move = config.default_worst_price_move
    worst_price = (
        min(ONE, reference_price + price_move)
        if signal.side == "BUY"
        else max(ZERO, reference_price - price_move)
    )
    rejection = _reject_reason(signal, market, config, decision_at)
    eligible_levels = _eligible_levels(signal.side, levels, worst_price)
    fill_size, fill_notional = _fill(
        eligible_levels,
        requested_size,
        maximum_notional=remaining_token_notional,
    )
    average_fill = fill_notional / fill_size if fill_size > ZERO else None

    if rejection is None and target_notional < config.minimum_notional:
        rejection = "token_exposure_limit"
    if rejection is None and order_type == "FOK" and fill_size < requested_size:
        rejection = "low_liquidity"
        fill_size, fill_notional, average_fill = ZERO, ZERO, None
    if rejection is None and fill_size <= ZERO:
        status = "created" if order_type == "GTC" else "rejected"
        rejection = None if order_type == "GTC" else "low_liquidity"
    elif rejection is not None:
        status = "rejected"
        fill_size, fill_notional, average_fill = ZERO, ZERO, None
    elif fill_size < requested_size:
        status = "would_partial_fill"
    else:
        status = "would_fill"

    slippage = ZERO
    if average_fill is not None:
        slippage = (
            average_fill - reference_price
            if signal.side == "BUY"
            else reference_price - average_fill
        )
    fee = fill_notional * config.fee_rate
    order_id = stable_uid(["paper_order", signal.signal_id, config.strategy_version, order_type])
    return PaperOrderDecision(
        order_id=order_id,
        signal_id=signal.signal_id,
        strategy_version=config.strategy_version,
        order_type=order_type,
        side=signal.side,
        market_id=signal.market_id,
        token_id=signal.token_id,
        requested_size=requested_size,
        requested_notional=target_notional,
        worst_price=worst_price,
        estimated_fill_price=average_fill,
        filled_size=fill_size,
        estimated_slippage=slippage,
        estimated_fee=fee,
        status=status,
        reject_reason=rejection,
        leader_trade_time=signal.leader_trade_time,
        signal_detected_at=signal.detected_at,
        decision_at=decision_at,
        order_simulated_at=simulated_at,
        detection_latency_ms=_milliseconds(signal.detected_at - signal.leader_trade_time),
        decision_latency_ms=_milliseconds(decision_at - signal.detected_at),
        simulation_latency_ms=_milliseconds(simulated_at - decision_at),
        orderbook_snapshot_uid=market.snapshot_uid,
        evidence={
            "available_levels": len(eligible_levels),
            "liquidity_score": market.liquidity_score,
            "spread_bps": market.spread_bps,
            "reference_price": reference_price,
            "signal_reason": signal.reason,
            "merged_signal_ids": signal.merged_signal_ids,
            "current_token_exposure": current_token_exposure,
            "maximum_token_notional": config.maximum_token_notional,
            "remaining_token_notional": remaining_token_notional,
        },
    )


def calculate_paper_pnl(
    *,
    side: Side,
    entry_price: Any,
    exit_price: Any,
    filled_size: Any,
    fee: Any,
    leader_price: Any,
) -> PaperPnl:
    entry = as_decimal(entry_price)
    exit_value = as_decimal(exit_price)
    size = as_decimal(filled_size)
    fee_value = as_decimal(fee)
    leader = as_decimal(leader_price)
    multiplier = ONE if side == "BUY" else Decimal("-1")
    gross = (exit_value - entry) * size * multiplier
    slippage_cost = abs(entry - leader) * size
    net = gross - fee_value
    direction_correct = (exit_value - leader) * multiplier > ZERO
    return PaperPnl(
        gross_pnl=gross,
        fee=fee_value,
        slippage_cost=slippage_cost,
        net_pnl=net,
        direction_correct=direction_correct,
        profitable_after_costs=net > ZERO,
    )


def _reject_reason(
    signal: Signal,
    market: MarketContext,
    config: StrategyConfig,
    decision_at: datetime,
) -> str | None:
    if market.compliance_blocked:
        return "compliance_block"
    if not market.metadata_available:
        return "market_metadata_missing"
    n_resolved = signal.evidence.get("n_resolved")
    if n_resolved is not None and as_decimal(n_resolved) < Decimal("10"):
        return "insufficient_score"
    if signal.score < config.minimum_score and signal.reason != "watchlist_wallet_trade":
        return "insufficient_score"
    if signal.confidence < config.minimum_confidence:
        return "low_confidence"
    if not market.accepting_orders:
        return "market_not_accepting_orders"
    if market.snapshot_at is None or decision_at - market.snapshot_at > config.maximum_book_age:
        return "stale_data"
    if decision_at - signal.detected_at > config.maximum_signal_age:
        return "late_signal"
    if market.end_date is not None and market.end_date - decision_at <= config.settlement_buffer:
        return "late_signal"
    if market.liquidity_score < config.minimum_liquidity_score:
        return "low_liquidity"
    if market.spread_bps is None or market.spread_bps > config.maximum_spread_bps:
        return "wide_spread"
    expected_edge = signal.evidence.get("expected_edge")
    if expected_edge is not None and as_decimal(expected_edge) <= ZERO:
        return "negative_expected_edge"
    direction = ONE if signal.side == "BUY" else Decimal("-1")
    if (
        expected_edge is None
        and market.midpoint is not None
        and (market.midpoint - signal.leader_price) * direction > config.default_worst_price_move
    ):
        return "negative_expected_edge"
    return None


def _eligible_levels(
    side: Side, levels: Sequence[BookLevel], worst_price: Decimal
) -> list[BookLevel]:
    if side == "BUY":
        return sorted(
            (row for row in levels if row.price <= worst_price), key=lambda row: row.price
        )
    return sorted(
        (row for row in levels if row.price >= worst_price), key=lambda row: row.price, reverse=True
    )


def _fill(
    levels: Sequence[BookLevel],
    requested_size: Decimal,
    *,
    maximum_notional: Decimal | None = None,
) -> tuple[Decimal, Decimal]:
    remaining = requested_size
    filled = ZERO
    notional = ZERO
    for level in levels:
        take = min(remaining, level.size)
        if maximum_notional is not None:
            remaining_notional = max(ZERO, maximum_notional - notional)
            if remaining_notional <= ZERO or level.price <= ZERO:
                break
            take = min(take, remaining_notional / level.price)
        filled += take
        notional += take * level.price
        remaining -= take
        if remaining <= ZERO:
            break
    return filled, notional


def _unit(value: Decimal) -> Decimal:
    return min(ONE, max(ZERO, value))


def _milliseconds(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() * 1000))
