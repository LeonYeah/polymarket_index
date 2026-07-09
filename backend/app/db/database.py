from __future__ import annotations

from sqlalchemy import Engine, create_engine

from backend.app.core.config import get_settings


def make_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    return create_engine(database_url or settings.database_url, future=True, pool_pre_ping=True)
