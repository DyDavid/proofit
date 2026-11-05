"""Phase 3 resource exhaustion protection tests.

Covers:
1. Streaming request/upload limits enforced during receiving and multipart parsing
   (without trusting Content-Length alone).
2. DOCX zip-bomb / decompression size / compression-ratio / path-traversal limits.
3. Process-isolated document parsing timeouts that genuinely terminate the worker PID.
4. Concurrent document parsing semaphore limits.
5. Bounded HTTP response downloads, including gzip/deflate decompression bombs.
6. Non-blocking async event loop during URL fetching and resume parsing.
7. Per-client sliding-window rate limiting on expensive public endpoints.
8. Bounded and expiring guest records (`guest_ip_usage`, guest `resumes`, guest `analyses`, `jobs`)
   and URL disk caches (`engine/ingest/cache.py`).
9. Preservation of normal PDF/DOCX uploads, job fetching, and the standard API error envelope.
"""

from __future__ import annotations

import asyncio
import gzip
import io
import json
import os
import socket
import time
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import docx
import httpx
import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.limiter import reset_rate_limits
from api.main import app
from api.store import store
from engine.ingest.cache import get_cached_text, prune_url_cache, save_cached_text
from engine.ingest.url_safety import UnsafeUrlError, safe_http_get
from engine.normalize.parser import (
    DecompressionLimitError,
    ParserConcurrencyError,
    ParserTimeoutError,
    parse_resume_bytes,
    parse_resume_bytes_async,
    run_parser_in_process_with_timeout,
    validate_docx_zip_safety,
)
from engine.normalize.schema import utcnow

client = TestClient(app)


# ── Top-level picklable helpers for child-process tests ─────────────────────


def _top_level_hanging_parser(file_bytes: bytes, filename: str) -> str:
    """Top-level picklable function that busy-loops to test process termination."""
    deadline = time.time() + 30.0
    acc = 0
    while time.time() < deadline:
        # Mix CPU work and tiny sleeps to simulate a stuck parser
        for i in range(10_000):
            acc += i
        time.sleep(0.01)
    return str(acc)


def _top_level_slow_parser(file_bytes: bytes, filename: str) -> str:
    """Top-level picklable function that sleeps briefly for concurrency testing."""
    time.sleep(0.35)
    return "parsed slow resume text"


def _is_pid_running(pid: int) -> bool:
    """Check whether a process with `pid` is still alive on Windows or POSIX."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return int(exit_code.value) == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True


def _build_valid_docx_bytes(text: str = "Sokha Chan — Junior Python & FastAPI Developer") -> bytes:
    buf = io.BytesIO()
    doc = docx.Document()
    doc.add_paragraph(text)
    doc.save(buf)
    return buf.getvalue()


def _build_minimal_pdf_bytes(text: str = "Sokha Chan Python Developer") -> bytes:
    """Build a small valid single-page PDF with extractable text."""
    stream_content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        f"4 0 obj\n<< /Length {len(stream_content)} >>\nstream\n".encode("latin-1")
        + stream_content
        + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objs:
        offsets.append(out.tell())
        out.write(obj)
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n".encode("latin-1"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return out.getvalue()


def _assert_error_envelope(response: Any, expected_status: int, expected_code: str) -> dict:
    assert response.status_code == expected_status
    body = response.json()
    assert set(body.keys()) == {"error"}
    err = body["error"]
    assert err["code"] == expected_code
    assert isinstance(err["message"], str) and len(err["message"]) > 0
    assert isinstance(err["error_id"], str) and err["error_id"].startswith("err_")
    return err


# ============================================================================
# 1. Streaming Request & Multipart Upload Limits (Without Trusting Content-Length)
# ============================================================================


def test_streaming_upload_aborts_mid_stream_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify ASGI receive() wrapper stops reading mid-stream when Content-Length is omitted
    or forged, rather than buffering the entire payload first.
    """
    monkeypatch.setattr(settings, "max_upload_bytes", 16 * 1024)  # 16 KB file limit

    chunks_consumed = 0
    total_chunks = 50  # 50 * 8 KB = 400 KB stream

    async def _run_raw_asgi() -> tuple[int, bytes]:
        nonlocal chunks_consumed

        async def mock_receive() -> dict[str, Any]:
            nonlocal chunks_consumed
            chunks_consumed += 1
            if chunks_consumed == 1:
                preamble = (
                    b"-----bound\r\n"
                    b'Content-Disposition: form-data; name="file"; filename="resume.pdf"\r\n'
                    b"Content-Type: application/pdf\r\n\r\n"
                    b"%PDF-1.4\n"
                )
                return {
                    "type": "http.request",
                    "body": preamble + (b"X" * 8000),
                    "more_body": True,
                }
            return {
                "type": "http.request",
                "body": b"X" * 8192,
                "more_body": chunks_consumed < total_chunks,
            }

        sent_messages: list[dict[str, Any]] = []

        async def mock_send(message: dict[str, Any]) -> None:
            sent_messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/resumes",
            "raw_path": b"/api/resumes",
            "query_string": b"",
            # Deliberately forge a tiny Content-Length of 100 bytes while streaming 400 KB
            "headers": [
                (b"content-type", b"multipart/form-data; boundary=---bound"),
                (b"content-length", b"100"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }

        await app(scope, mock_receive, mock_send)
        status = next(m["status"] for m in sent_messages if m["type"] == "http.response.start")
        body = b"".join(m.get("body", b"") for m in sent_messages if m["type"] == "http.response.body")
        return status, body

    status, raw_body = asyncio.run(_run_raw_asgi())
    assert status == 413
    payload = json.loads(raw_body.decode("utf-8"))
    assert payload["error"]["code"] == "RESUME_TOO_LARGE"
    assert payload["error"]["error_id"].startswith("err_")
    # Limit is 16 KB + 16 KB margin = 32 KB -> aborted at chunk 5 (40 KB), never reading all 50 chunks!
    assert chunks_consumed <= 6


def test_multipart_parser_aborts_on_part_data_when_file_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify MultiPartParser.on_part_data rejects a file exceeding max_upload_bytes by 1 byte."""
    monkeypatch.setattr(settings, "max_upload_bytes", 4096)
    oversized_pdf = b"%PDF-1.4\n" + (b"A" * 4096)  # 4105 bytes > 4096 limit
    res = client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", io.BytesIO(oversized_pdf), "application/pdf")},
    )
    _assert_error_envelope(res, 413, "RESUME_TOO_LARGE")


def test_oversized_content_length_rejected_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an oversized Content-Length header is rejected before reading any body chunk."""
    monkeypatch.setattr(settings, "max_upload_bytes", 1024)
    receive_called = False

    async def _run() -> int:
        nonlocal receive_called

        async def mock_receive() -> dict[str, Any]:
            nonlocal receive_called
            receive_called = True
            return {"type": "http.request", "body": b"should not be read", "more_body": False}

        sent: list[dict[str, Any]] = []

        async def mock_send(msg: dict[str, Any]) -> None:
            sent.append(msg)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/resumes",
            "raw_path": b"/api/resumes",
            "query_string": b"",
            "headers": [(b"content-length", str(10 * 1024 * 1024).encode("latin-1"))],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        await app(scope, mock_receive, mock_send)
        return next(m["status"] for m in sent if m["type"] == "http.response.start")

    status = asyncio.run(_run())
    assert status == 413
    assert receive_called is False


# ============================================================================
# 2. DOCX Decompression Limits & Zip Bomb Protection
# ============================================================================


def test_docx_decompressed_size_limit_blocks_zip_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a small compressed DOCX that expands beyond max_docx_decompressed_bytes is blocked."""
    monkeypatch.setattr(settings, "max_docx_decompressed_bytes", 32 * 1024)  # 32 KB decompressed limit

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 60 KB of XML content that compresses down to < 2 KB
        xml_payload = b"<w:document>" + (b"resume_line " * 5000) + b"</w:document>"
        zf.writestr("word/document.xml", xml_payload)
    bomb_bytes = buf.getvalue()
    assert len(bomb_bytes) < 5 * 1024  # tiny on the wire

    with pytest.raises(DecompressionLimitError):
        validate_docx_zip_safety(bomb_bytes)

    res = client.post(
        "/api/resumes",
        files={
            "file": (
                "bomb.docx",
                io.BytesIO(bomb_bytes),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    _assert_error_envelope(res, 413, "RESUME_TOO_LARGE")


def test_docx_high_compression_ratio_bomb_rejected() -> None:
    """Verify a zip entry with compression ratio > 100x is rejected even under total size cap."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 250 KB of zeroes compresses to ~300 bytes (ratio ~800:1 > 100:1 limit)
        zf.writestr("word/document.xml", b"0" * 250_000)
    bomb_bytes = buf.getvalue()

    with pytest.raises(DecompressionLimitError, match="compression ratio"):
        validate_docx_zip_safety(bomb_bytes)


def test_docx_path_traversal_member_rejected() -> None:
    """Verify a DOCX archive containing `..` path traversal entries is rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../../evil.xml", b"malicious")
    with pytest.raises(DecompressionLimitError, match="unsafe member path"):
        validate_docx_zip_safety(buf.getvalue())


# ============================================================================
# 3. Document Parsing Timeout & Guaranteed Process Termination
# ============================================================================


def test_timed_out_parsing_actually_terminates_worker_process() -> None:
    """Verify that when document parsing times out, the spawned child process is
    forcefully terminated and no longer running at the OS level.
    """
    with pytest.raises(ParserTimeoutError) as exc_info:
        run_parser_in_process_with_timeout(
            b"synthetic resume payload",
            "slow.pdf",
            timeout_seconds=0.25,
            custom_fn=_top_level_hanging_parser,
        )

    killed_pid = exc_info.value.pid
    assert killed_pid is not None and killed_pid > 0
    # Give OS a brief moment to reap the process handle
    time.sleep(0.05)
    assert _is_pid_running(killed_pid) is False

    # Verify subsequent normal parses recover seamlessly with a fresh worker process
    valid_docx = _build_valid_docx_bytes("Recovered Worker Resume — Python & SQL")
    extracted = run_parser_in_process_with_timeout(valid_docx, "resume.docx", timeout_seconds=5.0)
    assert "Recovered Worker Resume" in extracted


def test_resume_route_returns_422_resume_unreadable_on_parse_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify `/api/resumes` maps `ParserTimeoutError` to HTTP 422 `RESUME_UNREADABLE`."""

    async def _fake_timeout(*args: Any, **kwargs: Any) -> str:
        raise ParserTimeoutError("Timed out", pid=99999)

    monkeypatch.setattr("api.routes.resumes.parse_resume_bytes_async", _fake_timeout)
    res = client.post(
        "/api/resumes",
        files={"file": ("slow.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
    )
    _assert_error_envelope(res, 422, "RESUME_UNREADABLE")


# ============================================================================
# 4. Concurrent Document Parsing Limit
# ============================================================================


def test_concurrent_parsing_semaphore_blocks_excess_concurrency() -> None:
    """Verify that when `max_concurrency` slots are busy, additional parses fail fast
    with `ParserConcurrencyError`.
    """

    async def _run_concurrency_test() -> None:
        # Launch 2 slow parses with max_concurrency=1 and a short acquire_timeout
        t1 = asyncio.create_task(
            parse_resume_bytes_async(
                b"resume 1",
                "r1.pdf",
                timeout_seconds=5.0,
                max_concurrency=1,
                acquire_timeout=0.05,
                custom_fn=_top_level_slow_parser,
            )
        )
        await asyncio.sleep(0.05)
        with pytest.raises(ParserConcurrencyError):
            await parse_resume_bytes_async(
                b"resume 2",
                "r2.pdf",
                timeout_seconds=5.0,
                max_concurrency=1,
                acquire_timeout=0.05,
                custom_fn=_top_level_slow_parser,
            )
        res1 = await t1
        assert res1 == "parsed slow resume text"

    asyncio.run(_run_concurrency_test())


# ============================================================================
# 5. Bounded Downloaded Response Sizes (Including Decompressed Responses)
# ============================================================================


def _mock_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))],
    )


def test_safe_http_get_rejects_oversized_streaming_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify `safe_http_get` aborts streaming when body chunks exceed `max_response_bytes`."""
    _mock_public_dns(monkeypatch)
    chunks_sent = 0

    def _chunk_stream() -> Any:
        nonlocal chunks_sent
        for _ in range(50):
            chunks_sent += 1
            yield b"A" * 4096

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b"A" * (100 * 1024)))

    mock_transport = httpx.MockTransport(_handler)
    monkeypatch.setattr(
        "engine.ingest.url_safety.build_pinned_transport",
        lambda pinned_ips: (mock_transport, MagicMock()),
    )

    with pytest.raises(UnsafeUrlError, match="exceeded maximum limit"):
        safe_http_get("https://careers.example.com/job/1", max_response_bytes=16 * 1024)


def test_safe_http_get_rejects_gzip_decompression_bomb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify `safe_http_get` bounds decompressed size even when compressed wire bytes are tiny."""
    _mock_public_dns(monkeypatch)

    # 100 KB of repeated text compresses to < 500 bytes with gzip
    uncompressed = b"<html><body>" + (b"Job requirement line. " * 5000) + b"</body></html>"
    compressed = gzip.compress(uncompressed)
    assert len(compressed) < 1024  # under 1 KB on the wire!

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": str(len(compressed)),
            },
            stream=httpx.ByteStream(compressed),
        )

    mock_transport = httpx.MockTransport(_handler)
    monkeypatch.setattr(
        "engine.ingest.url_safety.build_pinned_transport",
        lambda pinned_ips: (mock_transport, MagicMock()),
    )

    # Wire size (< 1 KB) is well below max_response_bytes (16 KB), but decompressed (110 KB) exceeds it
    with pytest.raises(UnsafeUrlError, match="Decompressed response exceeded maximum limit"):
        safe_http_get("https://careers.example.com/job/gzip-bomb", max_response_bytes=16 * 1024)


def test_fetch_url_endpoint_rejects_oversized_upstream_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify `/api/jobs/fetch-url` returns standard envelope when upstream response exceeds limit."""
    _mock_public_dns(monkeypatch)
    monkeypatch.setattr(settings, "max_response_bytes", 8 * 1024)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body>" + (b"X" * 32768) + b"</body></html>")

    mock_transport = httpx.MockTransport(_handler)
    monkeypatch.setattr(
        "engine.ingest.url_safety.build_pinned_transport",
        lambda pinned_ips: (mock_transport, MagicMock()),
    )

    res = client.post("/api/jobs/fetch-url", json={"url": "https://careers.example.com/job/oversized"})
    _assert_error_envelope(res, 422, "JOB_URL_BLOCKED")


# ============================================================================
# 6. Event Loop Non-Blocking Verification
# ============================================================================


def test_event_loop_remains_responsive_during_slow_url_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify blocking network work in `/api/jobs/fetch-url` runs off the event loop."""

    def _slow_scrape(url: str) -> str:
        time.sleep(0.25)
        return "Software Engineer at Angkor Digital with 2 years of Python and FastAPI experience."

    monkeypatch.setattr("engine.ingest.scraper.scrape_job_url", _slow_scrape)

    async def _measure_heartbeat() -> float:
        max_tick_delay = 0.0
        done = False

        async def _heartbeat() -> None:
            nonlocal max_tick_delay
            while not done:
                t0 = time.perf_counter()
                await asyncio.sleep(0.01)
                dt = time.perf_counter() - t0
                if dt > max_tick_delay:
                    max_tick_delay = dt

        hb_task = asyncio.create_task(_heartbeat())
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                resp = await ac.post(
                    "/api/jobs/fetch-url",
                    json={"url": "https://careers.example.com/jobs/1"},
                )
                assert resp.status_code == 200
        finally:
            done = True
            await hb_task
        return max_tick_delay

    max_delay = asyncio.run(_measure_heartbeat())
    # If the 250ms blocking scrape ran on the event loop, max_delay would be >= 0.25s.
    assert max_delay < 0.12


# ============================================================================
# 7. Public Endpoint Rate Limiting
# ============================================================================


def test_rate_limiting_on_expensive_public_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify burst requests to `/api/jobs/fetch-url` and `/api/resumes` return 429 `RATE_LIMITED`."""
    reset_rate_limits()
    monkeypatch.setattr(settings, "rate_limit_fetch_per_min", 2)
    monkeypatch.setattr(settings, "rate_limit_resumes_per_min", 2)

    for _ in range(2):
        r = client.post("/api/jobs/fetch-url", json={"url": "http://localhost/blocked"})
        assert r.status_code == 422

    r_limited = client.post("/api/jobs/fetch-url", json={"url": "http://localhost/blocked"})
    _assert_error_envelope(r_limited, 429, "RATE_LIMITED")

    pdf_bytes = _build_minimal_pdf_bytes()
    for _ in range(2):
        r_res = client.post(
            "/api/resumes",
            files={"file": ("r.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r_res.status_code == 200

    r_res_limited = client.post(
        "/api/resumes",
        files={"file": ("r.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    _assert_error_envelope(r_res_limited, 429, "RATE_LIMITED")


def test_rate_limiter_bounds_internal_bucket_memory() -> None:
    """Verify `SlidingWindowRateLimiter` evicts old buckets when exceeding `max_buckets`."""
    from api.limiter import SlidingWindowRateLimiter

    small_limiter = SlidingWindowRateLimiter(max_buckets=5)
    for i in range(20):
        small_limiter.check(f"client-{i}", limit=3, window_seconds=60.0)
    assert small_limiter.bucket_count() <= 5


# ============================================================================
# 8. Bounding & Expiration of Guest Records and URL Disk Caches
# ============================================================================


def test_url_disk_cache_ttl_expiration_and_max_entries_bound(tmp_path: Path) -> None:
    """Verify `engine/ingest/cache.py` expires stale files and enforces `max_entries`."""
    key_expired = "https://example.com/jobs/expired"
    save_cached_text(key_expired, "Old job text", cache_dir=tmp_path, max_entries=5, ttl_seconds=10.0)

    # Backdate file mtime and cached_at to simulate expiration
    for p in tmp_path.glob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        data["cached_at"] = time.time() - 100.0
        p.write_text(json.dumps(data), encoding="utf-8")
        old_time = time.time() - 100.0
        os.utime(p, (old_time, old_time))

    assert get_cached_text(key_expired, cache_dir=tmp_path, ttl_seconds=10.0) is None

    # Save 8 entries with max_entries=3 and verify only 3 files remain on disk
    for i in range(8):
        save_cached_text(
            f"https://example.com/jobs/{i}",
            f"Job text {i}",
            cache_dir=tmp_path,
            max_entries=3,
            ttl_seconds=3600.0,
        )

    remaining_files = list(tmp_path.glob("*.json"))
    assert len(remaining_files) <= 3
    prune_url_cache(tmp_path, max_entries=2, ttl_seconds=3600.0)
    assert len(list(tmp_path.glob("*.json"))) <= 2


def test_store_prunes_expired_and_oversized_guest_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify `Store.prune_expired()` removes expired guest IPs, guest resumes, and guest analyses
    and enforces maximum capacity bounds.
    """
    now = utcnow()
    old_ts = now - timedelta(hours=30)

    # Seed expired guest IP, guest resume, and guest analysis
    store.guest_ip_usage["expired_ip_hash"] = old_ts
    expired_res = store.add_resume("old.pdf", "application/pdf", 10, data=b"old", user_id=None)
    expired_res.created_at = old_ts
    expired_an = store.create_analysis(expired_res.id, "job_1", "KH", user_id=None, is_guest=True)
    expired_an.created_at = old_ts

    store.prune_expired(now=now)
    assert "expired_ip_hash" not in store.guest_ip_usage
    assert expired_res.id not in store.resumes
    assert expired_an.id not in store.analyses

    # Verify capacity cap enforcement
    monkeypatch.setattr(store, "max_guest_resumes", 3)
    created_ids = []
    for i in range(6):
        r = store.add_resume(f"r{i}.pdf", "application/pdf", 10, data=b"x", user_id=None)
        created_ids.append(r.id)

    guest_resumes_in_mem = [r for r in store.resumes.values() if r.user_id is None]
    assert len(guest_resumes_in_mem) <= 3
    # Most recent 3 should be retained
    for recent_id in created_ids[-3:]:
        assert recent_id in store.resumes


# ============================================================================
# 9. Normal PDF/DOCX Uploads and Job Fetching Preserved
# ============================================================================


def test_normal_pdf_and_docx_uploads_succeed() -> None:
    """Verify valid PDF and DOCX resumes upload and extract text cleanly."""
    docx_bytes = _build_valid_docx_bytes("Dara Sok — Software Engineer skilled in Python and React")
    res_docx = client.post(
        "/api/resumes",
        files={
            "file": (
                "dara_resume.docx",
                io.BytesIO(docx_bytes),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res_docx.status_code == 200
    docx_id = res_docx.json()["resume_id"]
    rec_docx = store.get_resume(docx_id)
    assert rec_docx is not None
    assert rec_docx.raw_text is not None and "Dara Sok" in rec_docx.raw_text

    pdf_bytes = _build_minimal_pdf_bytes("Vanna Kem Backend Developer")
    res_pdf = client.post(
        "/api/resumes",
        files={"file": ("vanna_resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert res_pdf.status_code == 200
    pdf_id = res_pdf.json()["resume_id"]
    rec_pdf = store.get_resume(pdf_id)
    assert rec_pdf is not None
    assert rec_pdf.raw_text is not None and "Vanna Kem" in rec_pdf.raw_text

    # Direct parser call also works
    assert "Dara Sok" in parse_resume_bytes(docx_bytes, "dara_resume.docx")
