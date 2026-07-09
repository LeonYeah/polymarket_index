from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder

from backend.app.collectors.wallet_data import normalize_wallet_address
from backend.app.db.database import make_engine
from backend.app.db.wallet_repository import WalletDataRepository

router = APIRouter(prefix="/wallets", tags=["wallets"])


@router.get("/{wallet_address}/timeline")
def wallet_timeline(
    wallet_address: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    normalized_wallet = normalize_wallet_address(wallet_address) or wallet_address.lower()
    engine = make_engine()
    with engine.begin() as connection:
        repository = WalletDataRepository(connection)
        trades = repository.fetch_wallet_timeline(normalized_wallet, limit)
    return {
        "wallet_address": normalized_wallet,
        "limit": limit,
        "trades": jsonable_encoder(trades),
    }
