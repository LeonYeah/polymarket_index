from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder

from backend.app.db.database import make_engine
from backend.app.db.dashboard_repository import DashboardRepository
from backend.app.db.smart_score_repository import SmartScoreRepository

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("/leaderboard")
def score_leaderboard(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    high_confidence_only: bool = False,
) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = SmartScoreRepository(connection)
        rows = repository.fetch_leaderboard(
            limit=limit,
            offset=offset,
            high_confidence_only=high_confidence_only,
        )
        total = repository.count_leaderboard(high_confidence_only=high_confidence_only)
    return {
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(rows),
            "total": total,
            "has_more": offset + len(rows) < total,
        },
        "high_confidence_only": high_confidence_only,
        "amount_units": "USDC",
        "leaderboard": jsonable_encoder(rows),
    }


@router.get("/backtests/latest")
def latest_backtest_summary() -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = DashboardRepository(connection)
        row = repository.fetch_latest_backtest_summary()
    return {"amount_units": "USDC", "backtest": jsonable_encoder(row or {})}
