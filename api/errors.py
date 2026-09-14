"""Typed API errors and the response envelope (docs/errors.md §1).

Every error response from this API has exactly one shape:

    {"error": {"code": str, "message": str, "error_id": str}}

`code` is what the frontend switches on — never parse `message`. `message`
is English and developer-facing: it goes in logs, never to the user.
`error_id` is unique per occurrence and safe to show the user with a copy
button on an unrecoverable error, so a report can be traced back here.

Raise `ApiError` for any user-facing failure. Never raise a bare
`HTTPException` from a route — it would skip this envelope entirely.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("proofit.errors")


class ApiError(HTTPException):
    """A user-facing API error. `code` must be one of docs/errors.md §2's
    ten values — check that table before inventing an eleventh."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message


def new_error_id() -> str:
    return f"err_{secrets.token_hex(6)}"


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    error_id = new_error_id()
    logger.warning(
        "api_error code=%s error_id=%s path=%s message=%s",
        exc.code,
        error_id,
        request.url.path,
        exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "error_id": error_id}},
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
