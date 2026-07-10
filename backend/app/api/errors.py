from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def _payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details),
        },
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            code = str(detail.get("code") or f"http_{exc.status_code}")
            message = str(detail.get("message") or HTTPStatus(exc.status_code).phrase)
            details = {key: value for key, value in detail.items() if key not in {"code", "message"}}
        else:
            code = f"http_{exc.status_code}"
            message = str(detail or HTTPStatus(exc.status_code).phrase)
            details = None
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(code, message, details or None),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_payload("validation_error", "Request validation failed", exc.errors()),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=_payload("internal_error", "Internal server error"),
        )
