from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from backend.app.db.dashboard_repository import DashboardRepository
from backend.app.db.database import make_engine

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("")
def markets(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = DashboardRepository(connection)
        rows = repository.fetch_markets(limit=limit, offset=offset)
    return {
        "pagination": {"limit": limit, "offset": offset, "returned": len(rows)},
        "amount_units": "USDC",
        "markets": jsonable_encoder(rows),
    }


@router.get("/{market_id}")
def market_detail(market_id: str) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = DashboardRepository(connection)
        detail = repository.fetch_market_detail(market_id=market_id)
    if detail is None:
        raise HTTPException(status_code=404, detail={"code": "market_not_found"})
    return {
        "market_id": market_id,
        "amount_units": "USDC",
        "detail": jsonable_encoder(detail),
    }


@router.get("/{market_id}/smart-flow")
def market_smart_flow(
    market_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = DashboardRepository(connection)
        rows = repository.fetch_market_smart_flow(market_id=market_id, limit=limit)
    return {
        "market_id": market_id,
        "pagination": {"limit": limit, "offset": 0, "returned": len(rows)},
        "amount_units": "USDC",
        "smart_flow": jsonable_encoder(rows),
    }
