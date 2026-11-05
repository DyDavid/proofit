"""Request and multipart upload size limiting middleware (Phase 3).

Enforces size bounds at three layers without trusting Content-Length alone:
1. Immediate Content-Length header validation before reading body chunks.
2. Streaming ASGI `receive()` byte counter that aborts oversized chunked or
   forged-header streams mid-flight.
3. Multipart parser bounds (`max_files=1`, `max_fields=5`, and per-part
   streaming file byte cap at `settings.max_upload_bytes`) enforced inside
   `MultiPartParser.on_part_data` before buffering to disk or memory.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.config import settings
from api.errors import ApiError, new_error_id

logger = logging.getLogger("proofit.middleware")

# Margin for multipart boundaries and part headers around a single file upload
MULTIPART_HEADER_MARGIN_BYTES = 16 * 1024  # 16 KB
# Max body size for non-upload JSON endpoints (/api/jobs, /api/analyses, etc.)
MAX_JSON_BODY_BYTES = 256 * 1024  # 256 KB
MAX_MULTIPART_FILES = 1
MAX_MULTIPART_FIELDS = 5
MAX_PART_HEADER_BYTES = 8 * 1024


class _StreamLimitExceededError(Exception):
    """Raised when an incoming request stream exceeds the allowed byte limit."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _install_bounded_multipart_parser() -> None:
    """Patch Starlette's MultiPartParser to enforce file size and part count limits
    during multipart parsing (`on_part_data`), rather than after reading the full stream.
    """
    if getattr(MultiPartParser, "_proofit_bounded", False):
        return

    orig_init = MultiPartParser.__init__
    orig_on_part_begin = MultiPartParser.on_part_begin
    orig_on_part_data = MultiPartParser.on_part_data
    orig_on_header_field = MultiPartParser.on_header_field
    orig_on_header_value = MultiPartParser.on_header_value

    def bounded_init(
        self: MultiPartParser,
        headers: Any,
        stream: Any,
        *,
        max_files: int | float = MAX_MULTIPART_FILES,
        max_fields: int | float = MAX_MULTIPART_FIELDS,
        max_part_size: int = 64 * 1024,
    ) -> None:
        orig_init(
            self,
            headers,
            stream,
            max_files=min(max_files, MAX_MULTIPART_FILES),
            max_fields=min(max_fields, MAX_MULTIPART_FIELDS),
            max_part_size=max_part_size,
        )
        self._current_part_bytes = 0
        self._header_bytes = 0

    def bounded_on_part_begin(self: MultiPartParser) -> None:
        orig_on_part_begin(self)
        self._current_part_bytes = 0

    def bounded_on_header_field(self: MultiPartParser, data: bytes, start: int, end: int) -> None:
        self._header_bytes = getattr(self, "_header_bytes", 0) + (end - start)
        if self._header_bytes > MAX_PART_HEADER_BYTES:
            raise MultiPartException("Multipart headers exceeded maximum allowed size.")
        orig_on_header_field(self, data, start, end)

    def bounded_on_header_value(self: MultiPartParser, data: bytes, start: int, end: int) -> None:
        self._header_bytes = getattr(self, "_header_bytes", 0) + (end - start)
        if self._header_bytes > MAX_PART_HEADER_BYTES:
            raise MultiPartException("Multipart headers exceeded maximum allowed size.")
        orig_on_header_value(self, data, start, end)

    def bounded_on_part_data(self: MultiPartParser, data: bytes, start: int, end: int) -> None:
        chunk_len = end - start
        if self._current_part.file is not None:
            self._current_part_bytes = getattr(self, "_current_part_bytes", 0) + chunk_len
            max_bytes = settings.max_upload_bytes
            if self._current_part_bytes > max_bytes:
                raise ApiError(
                    status_code=413,
                    code="RESUME_TOO_LARGE",
                    message=f"Upload exceeds {max_bytes} bytes.",
                )
        orig_on_part_data(self, data, start, end)

    MultiPartParser.__init__ = bounded_init  # type: ignore[method-assign]
    MultiPartParser.on_part_begin = bounded_on_part_begin  # type: ignore[method-assign]
    MultiPartParser.on_part_data = bounded_on_part_data  # type: ignore[method-assign]
    MultiPartParser.on_header_field = bounded_on_header_field  # type: ignore[method-assign]
    MultiPartParser.on_header_value = bounded_on_header_value  # type: ignore[method-assign]
    MultiPartParser._proofit_bounded = True  # type: ignore[attr-defined]


_install_bounded_multipart_parser()


class RequestSizeLimitMiddleware:
    """ASGI middleware that bounds incoming request bodies during streaming `receive()`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def _route_limits(self, path: str) -> tuple[int, int, str]:
        """Return `(max_stream_bytes, reported_limit_bytes, error_code)` for `path`."""
        if path.rstrip("/") == "/api/resumes":
            max_upload = settings.max_upload_bytes
            return (
                max_upload + MULTIPART_HEADER_MARGIN_BYTES,
                max_upload,
                "RESUME_TOO_LARGE",
            )
        if path.startswith("/api/jobs"):
            return (MAX_JSON_BODY_BYTES, MAX_JSON_BODY_BYTES, "JOB_EMPTY")
        return (MAX_JSON_BODY_BYTES, MAX_JSON_BODY_BYTES, "RESUME_TOO_LARGE")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        max_stream_bytes, reported_limit, error_code = self._route_limits(path)

        # 1. Fast-fail if Content-Length header already exceeds the route threshold
        headers = dict(scope.get("headers") or [])
        raw_cl = headers.get(b"content-length")
        if raw_cl is not None:
            try:
                cl_val = int(raw_cl.decode("latin-1").strip())
                if cl_val < 0:
                    raise ValueError("Negative Content-Length")
                if cl_val > max_stream_bytes:
                    await self._send_error(
                        scope,
                        receive,
                        send,
                        status_code=413,
                        code=error_code,
                        message=f"Upload exceeds {reported_limit} bytes.",
                    )
                    return
            except ValueError:
                await self._send_error(
                    scope,
                    receive,
                    send,
                    status_code=422,
                    code=error_code,
                    message="Invalid Content-Length header.",
                )
                return

        # 2. Wrap receive() to count actual bytes streamed over the wire
        received_bytes = 0
        response_started = False

        async def wrapped_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                received_bytes += len(chunk)
                if received_bytes > max_stream_bytes:
                    raise _StreamLimitExceededError(
                        status_code=413,
                        code=error_code,
                        message=f"Upload exceeds {reported_limit} bytes.",
                    )
            return message

        try:
            await self.app(scope, limited_receive, wrapped_send)
        except _StreamLimitExceededError as exc:
            if not response_started:
                await self._send_error(
                    scope,
                    receive,
                    send,
                    status_code=exc.status_code,
                    code=exc.code,
                    message=exc.message,
                )
        except ApiError as exc:
            if not response_started:
                await self._send_error(
                    scope,
                    receive,
                    send,
                    status_code=exc.status_code,
                    code=exc.code,
                    message=exc.message,
                )

    @staticmethod
    async def _send_error(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        error_id = new_error_id()
        logger.warning(
            "api_error code=%s error_id=%s path=%s message=%s",
            code,
            error_id,
            scope.get("path", ""),
            message,
        )
        response = JSONResponse(
            status_code=status_code,
            content={"error": {"code": code, "message": message, "error_id": error_id}},
        )
        await response(scope, receive, send)

