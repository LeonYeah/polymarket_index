from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any


ZERO = Decimal("0")
ONE = Decimal("1")


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


def utc_now() -> datetime:
    return datetime.now(UTC)


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == ZERO:
        return None
    return numerator / denominator


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _is_taker_trade(row: Mapping[str, Any], wallet_address: str) -> bool:
    raw = row.get("raw")
    raw_map = raw if isinstance(raw, Mapping) else {}
    wallet = wallet_address.lower()
    taker = str(raw_map.get("taker") or raw_map.get("takerWallet") or "").lower()
    role = str(raw_map.get("role") or raw_map.get("liquidity") or "").lower()
    return taker == wallet or role == "taker"


@dataclass(frozen=True)
class PnLInput:
    wallet_address: str
    trades: list[Mapping[str, Any]] = field(default_factory=list)
    current_positions: list[Mapping[str, Any]] = field(default_factory=list)
    closed_positions: list[Mapping[str, Any]] = field(default_factory=list)
    market_statuses: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class PnLResult:
    wallet_market_results: list[dict[str, Any]]
    wallet_daily_equity: list[dict[str, Any]]
    reconciliation_checks: list[dict[str, Any]]


@dataclass(frozen=True)
class PnLRunResult:
    run_id: str
    status: str
    counters: dict[str, int]
    started_at: datetime
    finished_at: datetime
    wallet_profiles: list[dict[str, Any]] = field(default_factory=list)


def calculate_wallet_pnl(
    pnl_input: PnLInput,
    *,
    run_id: str,
    calculated_at: datetime | None = None,
    reconciliation_limit: int = 30,
    source: str = "pnl_engine_v1",
) -> PnLResult:
    calculated_at = calculated_at or utc_now()
    grouped = _group_inputs(pnl_input)
    results = [
        _calculate_market_result(
            wallet_address=pnl_input.wallet_address,
            key=key,
            rows=rows,
            market_status=pnl_input.market_statuses.get(key[0] or ""),
            run_id=run_id,
            calculated_at=calculated_at,
            source=source,
        )
        for key, rows in sorted(grouped.items(), key=lambda item: _sort_key(item[0]))
    ]
    daily_equity = _calculate_daily_equity(
        wallet_address=pnl_input.wallet_address,
        trades=pnl_input.trades,
        closed_positions=pnl_input.closed_positions,
        results=results,
        run_id=run_id,
        calculated_at=calculated_at,
        source=source,
    )
    reconciliation = _build_reconciliation_checks(
        wallet_address=pnl_input.wallet_address,
        results=results,
        closed_positions=pnl_input.closed_positions,
        run_id=run_id,
        checked_at=calculated_at,
        limit=reconciliation_limit,
        source=source,
    )
    return PnLResult(results, daily_equity, reconciliation)


def _group_inputs(pnl_input: PnLInput) -> dict[tuple[str | None, str | None, str | None], dict[str, list[Mapping[str, Any]]]]:
    grouped: dict[tuple[str | None, str | None, str | None], dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: {"trades": [], "current_positions": [], "closed_positions": []}
    )
    for trade in pnl_input.trades:
        key = (
            _nullable_text(trade.get("condition_id")),
            _nullable_text(trade.get("token_id")),
            _nullable_text(trade.get("outcome")),
        )
        grouped[key]["trades"].append(trade)
    for position in pnl_input.current_positions:
        key = (
            _nullable_text(position.get("condition_id")),
            _nullable_text(position.get("token_id")),
            _nullable_text(position.get("outcome")),
        )
        grouped[key]["current_positions"].append(position)
    for position in pnl_input.closed_positions:
        key = (
            _nullable_text(position.get("condition_id")),
            _nullable_text(position.get("token_id")),
            _nullable_text(position.get("outcome")),
        )
        grouped[key]["closed_positions"].append(position)
    return grouped


def _calculate_market_result(
    *,
    wallet_address: str,
    key: tuple[str | None, str | None, str | None],
    rows: Mapping[str, list[Mapping[str, Any]]],
    market_status: Mapping[str, Any] | None,
    run_id: str,
    calculated_at: datetime,
    source: str,
) -> dict[str, Any]:
    condition_id, token_id, outcome = key
    trades = rows["trades"]
    current_positions = rows["current_positions"]
    closed_positions = rows["closed_positions"]

    buy_trades = [trade for trade in trades if _upper(trade.get("side")) == "BUY"]
    sell_trades = [trade for trade in trades if _upper(trade.get("side")) == "SELL"]
    total_buy_size = sum((as_decimal(trade.get("size")) for trade in buy_trades), ZERO)
    total_sell_size = sum((as_decimal(trade.get("size")) for trade in sell_trades), ZERO)
    total_buy_notional = sum((_trade_notional(trade) for trade in buy_trades), ZERO)
    total_sell_notional = sum((_trade_notional(trade) for trade in sell_trades), ZERO)
    current_value = sum((as_decimal(position.get("current_value")) for position in current_positions), ZERO)
    current_cash_pnl = sum((as_decimal(position.get("cash_pnl")) for position in current_positions), ZERO)
    closed_realized_pnl = sum((as_decimal(position.get("realized_pnl")) for position in closed_positions), ZERO)
    open_size = sum((as_decimal(position.get("size")) for position in current_positions), ZERO)
    if not current_positions:
        open_size = total_buy_size - total_sell_size
    capital_deployed = max(total_buy_notional - total_sell_notional, ZERO)
    realized_pnl = closed_realized_pnl
    unrealized_pnl = current_cash_pnl
    estimated_fees = ZERO
    estimated_slippage = ZERO
    net_pnl = realized_pnl + unrealized_pnl - estimated_fees - estimated_slippage
    gross_pnl = realized_pnl + unrealized_pnl
    avg_buy_price = _safe_divide(total_buy_notional, total_buy_size)
    avg_sell_price = _safe_divide(total_sell_notional, total_sell_size)
    gross_roi = _safe_divide(gross_pnl, capital_deployed)
    net_roi = _safe_divide(net_pnl, capital_deployed)
    timestamps = [
        timestamp
        for timestamp in (trade.get("trade_timestamp") for trade in trades)
        if isinstance(timestamp, datetime)
    ]
    entry_time = min(timestamps) if timestamps else None
    exit_time = _exit_time(trades, closed_positions)
    holding_seconds = (
        int((exit_time - entry_time).total_seconds())
        if entry_time is not None and exit_time is not None and exit_time >= entry_time
        else None
    )
    taker_trade_count = sum(1 for trade in trades if _is_taker_trade(trade, wallet_address))
    market_status_text = _market_status_text(market_status)
    result_status = _result_status(market_status_text, open_size, closed_positions, condition_id, token_id)
    outcome_correct = _outcome_correct(closed_positions, market_status_text)

    return {
        "result_uid": stable_uid(["wallet_market_result", wallet_address, condition_id, token_id, outcome]),
        "wallet_address": wallet_address,
        "condition_id": condition_id,
        "token_id": token_id,
        "outcome": outcome,
        "market_status": market_status_text,
        "result_status": result_status,
        "outcome_correct": outcome_correct,
        "trade_count": len(trades),
        "buy_count": len(buy_trades),
        "sell_count": len(sell_trades),
        "taker_trade_count": taker_trade_count,
        "total_buy_size": total_buy_size,
        "total_sell_size": total_sell_size,
        "total_buy_notional": total_buy_notional,
        "total_sell_notional": total_sell_notional,
        "avg_buy_price": avg_buy_price,
        "avg_sell_price": avg_sell_price,
        "open_size": open_size,
        "capital_deployed": capital_deployed,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "current_value": current_value,
        "estimated_fees": estimated_fees,
        "estimated_slippage": estimated_slippage,
        "fees_estimated": True,
        "slippage_estimated": True,
        "fee_risk_level": "higher" if taker_trade_count else "unknown",
        "net_pnl": net_pnl,
        "gross_roi": gross_roi,
        "net_roi": net_roi,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "holding_duration_seconds": holding_seconds,
        "calculation_notes": {
            "realized_pnl_source": "wallet_positions_closed.realized_pnl",
            "unrealized_pnl_source": "wallet_positions_current.cash_pnl",
            "current_value_is_not_realized": True,
            "fee_model": "placeholder_zero_until_orderbook_week05",
        },
        "calculated_at": calculated_at,
        "source": source,
        "ingestion_run_id": run_id,
    }


def _calculate_daily_equity(
    *,
    wallet_address: str,
    trades: list[Mapping[str, Any]],
    closed_positions: list[Mapping[str, Any]],
    results: list[Mapping[str, Any]],
    run_id: str,
    calculated_at: datetime,
    source: str,
) -> list[dict[str, Any]]:
    daily_volume: dict[date, Decimal] = defaultdict(lambda: ZERO)
    daily_trade_count: dict[date, int] = defaultdict(int)
    daily_realized: dict[date, Decimal] = defaultdict(lambda: ZERO)
    dates: set[date] = {calculated_at.date()}

    for trade in trades:
        trade_date = _date(trade.get("trade_timestamp"))
        if trade_date is None:
            continue
        dates.add(trade_date)
        daily_volume[trade_date] += _trade_notional(trade)
        daily_trade_count[trade_date] += 1
    for position in closed_positions:
        closed_date = _date(position.get("closed_at"))
        if closed_date is None:
            continue
        dates.add(closed_date)
        daily_realized[closed_date] += as_decimal(position.get("realized_pnl"))

    unrealized_today = sum((as_decimal(result.get("unrealized_pnl")) for result in results), ZERO)
    capital_deployed = sum((as_decimal(result.get("capital_deployed")) for result in results), ZERO)
    cumulative_realized = ZERO
    peak = ZERO
    max_drawdown = ZERO
    rows: list[dict[str, Any]] = []
    for equity_date in sorted(dates):
        cumulative_realized += daily_realized[equity_date]
        unrealized = unrealized_today if equity_date == calculated_at.date() else ZERO
        net_pnl = cumulative_realized + unrealized
        if not rows or net_pnl > peak:
            peak = net_pnl
        drawdown = peak - net_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown
        rows.append(
            {
                "wallet_address": wallet_address,
                "equity_date": equity_date,
                "realized_pnl_cumulative": cumulative_realized,
                "unrealized_pnl": unrealized,
                "net_pnl": net_pnl,
                "capital_deployed": capital_deployed,
                "daily_volume": daily_volume[equity_date],
                "trades_count": daily_trade_count[equity_date],
                "drawdown": drawdown,
                "max_drawdown": max_drawdown,
                "calculated_at": calculated_at,
                "source": source,
                "ingestion_run_id": run_id,
            }
        )
    return rows


def _build_reconciliation_checks(
    *,
    wallet_address: str,
    results: list[Mapping[str, Any]],
    closed_positions: list[Mapping[str, Any]],
    run_id: str,
    checked_at: datetime,
    limit: int,
    source: str,
) -> list[dict[str, Any]]:
    closed_by_key: dict[tuple[str | None, str | None], Decimal] = defaultdict(lambda: ZERO)
    for position in closed_positions:
        key = (_nullable_text(position.get("condition_id")), _nullable_text(position.get("token_id")))
        closed_by_key[key] += as_decimal(position.get("realized_pnl"))

    checks: list[dict[str, Any]] = []
    for result in results:
        if len(checks) >= limit:
            break
        key = (_nullable_text(result.get("condition_id")), _nullable_text(result.get("token_id")))
        if key not in closed_by_key:
            continue
        engine_value = as_decimal(result.get("realized_pnl"))
        source_value = closed_by_key[key]
        difference = engine_value - source_value
        tolerance = Decimal("0.000001")
        status = "matched" if abs(difference) <= tolerance else "different"
        diff_category = "matched" if status == "matched" else "unknown"
        checks.append(
            {
                "wallet_address": wallet_address,
                "condition_id": result.get("condition_id"),
                "token_id": result.get("token_id"),
                "check_type": "closed_position_realized_pnl",
                "status": status,
                "diff_category": diff_category,
                "engine_realized_pnl": engine_value,
                "source_realized_pnl": source_value,
                "difference": difference,
                "tolerance": tolerance,
                "details": {
                    "source": "wallet_positions_closed",
                    "difference_categories": [
                        "field_missing",
                        "time_window_different",
                        "fee_basis_different",
                        "mapping_failed",
                        "unknown",
                    ],
                },
                "checked_at": checked_at,
                "source": source,
                "ingestion_run_id": run_id,
            }
        )
    return checks


def summarize_wallet_profile(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    realized_pnl = sum((as_decimal(row.get("realized_pnl")) for row in rows), ZERO)
    unrealized_pnl = sum((as_decimal(row.get("unrealized_pnl")) for row in rows), ZERO)
    net_pnl = sum((as_decimal(row.get("net_pnl")) for row in rows), ZERO)
    capital_deployed = sum((as_decimal(row.get("capital_deployed")) for row in rows), ZERO)
    wins = [row for row in rows if as_decimal(row.get("realized_pnl")) > ZERO]
    losses = [row for row in rows if as_decimal(row.get("realized_pnl")) < ZERO]
    gross_profit = sum((as_decimal(row.get("realized_pnl")) for row in wins), ZERO)
    gross_loss = abs(sum((as_decimal(row.get("realized_pnl")) for row in losses), ZERO))
    best_market_pnl = max((as_decimal(row.get("realized_pnl")) for row in rows), default=ZERO)
    profit_factor = _safe_divide(gross_profit, gross_loss)
    return {
        "markets_count": len(rows),
        "closed_markets_count": sum(1 for row in rows if row.get("result_status") in {"closed", "settled"}),
        "open_markets_count": sum(1 for row in rows if row.get("result_status") == "open"),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "net_pnl": net_pnl,
        "capital_deployed": capital_deployed,
        "net_roi": _safe_divide(net_pnl, capital_deployed),
        "win_rate": _safe_divide(Decimal(len(wins)), Decimal(len(wins) + len(losses))),
        "profit_factor": profit_factor,
        "single_market_profit_share": _safe_divide(best_market_pnl, gross_profit),
    }


def _trade_notional(trade: Mapping[str, Any]) -> Decimal:
    notional = as_decimal(trade.get("notional"))
    if notional != ZERO:
        return notional
    return as_decimal(trade.get("price")) * as_decimal(trade.get("size"))


def _exit_time(trades: list[Mapping[str, Any]], closed_positions: list[Mapping[str, Any]]) -> datetime | None:
    closed_times = [
        timestamp
        for timestamp in (position.get("closed_at") for position in closed_positions)
        if isinstance(timestamp, datetime)
    ]
    if closed_times:
        return max(closed_times)
    sell_times = [
        timestamp
        for timestamp in (trade.get("trade_timestamp") for trade in trades if _upper(trade.get("side")) == "SELL")
        if isinstance(timestamp, datetime)
    ]
    return max(sell_times) if sell_times else None


def _market_status_text(market_status: Mapping[str, Any] | None) -> str:
    if not market_status:
        return "unknown"
    status = str(market_status.get("status") or "").strip().lower()
    return status or "unknown"


def _result_status(
    market_status: str,
    open_size: Decimal,
    closed_positions: list[Mapping[str, Any]],
    condition_id: str | None,
    token_id: str | None,
) -> str:
    if not condition_id or not token_id:
        return "mapping_failed"
    if market_status in {"cancelled", "disputed", "archived"}:
        return market_status
    if open_size > ZERO:
        return "open"
    if closed_positions:
        return "settled" if market_status in {"closed", "resolved", "settled"} else "closed"
    return "unknown"


def _outcome_correct(closed_positions: list[Mapping[str, Any]], market_status: str) -> bool | None:
    if market_status not in {"closed", "resolved", "settled"} or not closed_positions:
        return None
    prices = [as_decimal(position.get("cur_price"), default=Decimal("-1")) for position in closed_positions]
    if any(price >= Decimal("0.99") for price in prices):
        return True
    if all(ZERO <= price <= Decimal("0.01") for price in prices):
        return False
    return None


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sort_key(key: tuple[str | None, str | None, str | None]) -> tuple[str, str, str]:
    return tuple(value or "" for value in key)
