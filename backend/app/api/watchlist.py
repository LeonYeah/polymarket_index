from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from backend.app.collectors.wallet_data import normalize_wallet_address
from backend.app.db.dashboard_repository import DashboardRepository
from backend.app.db.database import make_engine

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistWalletCreate(BaseModel):
    wallet_address: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=500)
    operator: str = Field(default="local", min_length=1, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WatchlistMarketCreate(BaseModel):
    condition_id: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=500)
    operator: str = Field(default="local", min_length=1, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/wallets", status_code=201)
def add_watchlist_wallet(payload: WatchlistWalletCreate) -> dict[str, Any]:
    normalized_wallet = normalize_wallet_address(payload.wallet_address) or payload.wallet_address.lower()
    row_payload = payload.model_dump()
    row_payload["wallet_address"] = normalized_wallet
    engine = make_engine()
    with engine.begin() as connection:
        repository = DashboardRepository(connection)
        row = repository.add_watchlist_wallet(row_payload)
    return {"watchlist_wallet": jsonable_encoder(row)}


@router.post("/markets", status_code=201)
def add_watchlist_market(payload: WatchlistMarketCreate) -> dict[str, Any]:
    engine = make_engine()
    with engine.begin() as connection:
        repository = DashboardRepository(connection)
        row = repository.add_watchlist_market(payload.model_dump())
    return {"watchlist_market": jsonable_encoder(row)}
