from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from backend.app.analytics.paper_trading_runner import run_paper_trading
from backend.app.db.database import make_engine
from backend.app.db.paper_trading_repository import PaperTradingRepository

router = APIRouter(prefix="/paper", tags=["paper-trading"])


class PaperRunRequest(BaseModel):
    lookback_minutes: int = Field(default=60, ge=1, le=10_080)
    signal_limit: int = Field(default=500, ge=1, le=5000)
    valuation_limit: int = Field(default=1000, ge=1, le=10_000)
    order_type: Literal["FOK", "FAK", "GTC"] = "FAK"


@router.get("/summary")
def paper_summary() -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        summary = PaperTradingRepository(connection).fetch_summary()
    return {
        "amount_units": "USDC",
        "strategy_version": "weighted_copy_v1",
        "summary": jsonable_encoder(summary),
        "sampling_note": (
            "The seven-day and 100-order acceptance thresholds require continued scheduled runs."
        ),
    }


@router.get("/health")
def sampling_health(
    max_age_seconds: Annotated[int, Query(ge=30, le=86_400)] = 300,
) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        health = PaperTradingRepository(connection).fetch_sampling_health(
            max_age_seconds=max_age_seconds
        )
    return jsonable_encoder(health)


@router.get("/signals")
def paper_signals(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = PaperTradingRepository(connection)
        rows = repository.fetch_signals(limit=limit, offset=offset)
        total = repository.count_signals()
    return {
        "pagination": _pagination(limit, offset, len(rows), total),
        "amount_units": "USDC",
        "signals": jsonable_encoder(rows),
    }


@router.get("/orders")
def paper_orders(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = PaperTradingRepository(connection)
        rows = repository.fetch_orders(limit=limit, offset=offset)
        total = repository.count_orders()
    return {
        "pagination": _pagination(limit, offset, len(rows), total),
        "amount_units": "USDC",
        "orders": jsonable_encoder(rows),
    }


@router.post("/run")
def run_paper_cycle(payload: PaperRunRequest) -> dict[str, Any]:
    result = run_paper_trading(
        make_engine(),
        lookback_minutes=payload.lookback_minutes,
        signal_limit=payload.signal_limit,
        valuation_limit=payload.valuation_limit,
        order_type=payload.order_type,
    )
    return jsonable_encoder(result.__dict__)


def _pagination(limit: int, offset: int, returned: int, total: int) -> dict[str, Any]:
    return {
        "limit": limit,
        "offset": offset,
        "returned": returned,
        "total": total,
        "has_more": offset + returned < total,
    }
