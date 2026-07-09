from fastapi import FastAPI

from backend.app.api.health import router as health_router
from backend.app.api.wallets import router as wallets_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Polymarket Wallet Tracker",
        version="0.1.0",
        description="Read-only API for Polymarket wallet research workflows.",
    )
    app.include_router(health_router)
    app.include_router(wallets_router)
    return app


app = create_app()
