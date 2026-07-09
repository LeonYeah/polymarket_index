from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from backend.app.collectors.wallet_data import normalize_wallet_address
from backend.app.db.dashboard_repository import DashboardRepository
from backend.app.db.database import make_engine

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertStatusUpdate(BaseModel):
    status: Literal["open", "ack", "resolved"]
    operator: str = Field(default="local", min_length=1, max_length=120)


@router.get("")
def alerts(
    status: Literal["open", "ack", "resolved"] | None = "open",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    generate: bool = True,
    condition_id: str | None = None,
    wallet_address: str | None = None,
) -> dict[str, Any]:
    normalized_wallet = None
    if wallet_address:
        normalized_wallet = normalize_wallet_address(wallet_address) or wallet_address.lower()
    engine = make_engine()
    with engine.begin() as connection:
        repository = DashboardRepository(connection)
        generation = repository.generate_alerts() if generate else {}
        rows = repository.fetch_alerts(
            status=status,
            limit=limit,
            offset=offset,
            condition_id=condition_id,
            wallet_address=normalized_wallet,
        )
    return {
        "pagination": {"limit": limit, "offset": offset, "returned": len(rows)},
        "status": status,
        "generated": generation,
        "alerts": jsonable_encoder(rows),
    }


@router.patch("/{alert_id}")
def update_alert(alert_id: str, payload: AlertStatusUpdate) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = DashboardRepository(connection)
        row = repository.update_alert_status(
            alert_id=alert_id,
            status=payload.status,
            operator=payload.operator,
        )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "alert_not_found"})
    return {"alert": jsonable_encoder(row)}
