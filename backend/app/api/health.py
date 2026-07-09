from datetime import UTC, datetime

from fastapi import APIRouter

from backend.app.core.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }

