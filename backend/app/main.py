from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.alerts import router as alerts_router
from backend.app.api.errors import register_error_handlers
from backend.app.api.health import router as health_router
from backend.app.api.markets import router as markets_router
from backend.app.api.paper import router as paper_router
from backend.app.api.scores import router as scores_router
from backend.app.api.watchlist import router as watchlist_router
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(wallets_router)
    app.include_router(scores_router)
    app.include_router(markets_router)
    app.include_router(paper_router)
    app.include_router(alerts_router)
    app.include_router(watchlist_router)
    return app


app = create_app()
