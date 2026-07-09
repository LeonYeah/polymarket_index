from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiRequestRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    source: str
    endpoint: str
    params: dict[str, Any] = Field(default_factory=dict)
    status_code: int | None = None
    ok: bool
    duration_ms: int
    error: str | None = None
    sample_path: str | None = None


class MarketRef(BaseModel):
    condition_id: str | None = None
    market_slug: str | None = None
    question: str | None = None
    clob_token_ids: list[str] = Field(default_factory=list)
    active: bool | None = None
    closed: bool | None = None


class WalletPosition(BaseModel):
    wallet_address: str
    market: str | None = None
    outcome: str | None = None
    size: Decimal | None = None
    current_value: Decimal | None = None
    updated_at_utc: datetime | None = None

