from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder

from backend.app.db.database import make_engine
from backend.app.db.smart_score_repository import SmartScoreRepository

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("/leaderboard")
def score_leaderboard(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    high_confidence_only: bool = False,
) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = SmartScoreRepository(connection)
        rows = repository.fetch_leaderboard(
            limit=limit,
            high_confidence_only=high_confidence_only,
        )
    return {
        "limit": limit,
        "high_confidence_only": high_confidence_only,
        "leaderboard": jsonable_encoder(rows),
    }
