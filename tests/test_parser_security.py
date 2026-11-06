"""Small PDF fixtures and OS-limited workers; never exhaust the test host."""

import builtins
import zlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from parser_helpers import allocate_too_much, missing_parser_dependency

from api.config import settings
from api.main import app
from api.routes import resumes
from engine.normalize import parser
from engine.normalize.memory_limit import limit_process_memory


def make_pdf(streams):
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"]
    contents = b" ".join(f"{index + 4} 0 R".encode() for index in range(len(streams)))
    font_id = len(streams) + 4
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << /Font << /F1 "
                   + str(font_id).encode() + b" 0 R >> >> /Contents [" + contents + b"] >>")
    for stream in streams:
        compressed = zlib.compress(stream)
        objects.append(b"<< /Length " + str(len(compressed)).encode() + b" /Filter /FlateDecode >>\nstream\n"
                       + compressed + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Root 1 0 R /Size {len(objects)+1} >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(data)


def test_pdf_expansion_is_rejected_without_text_fallback(monkeypatch):
    monkeypatch.setattr(settings, "max_pdf_decompressed_bytes", 1024 * 1024)
    data = make_pdf([b" " * (2 * 1024 * 1024)])
    assert len(data) < 6000
    with pytest.raises(parser.DecompressionLimitError):
        parser.parse_resume_bytes(data, "small.pdf")


def test_pdf_budget_is_total_across_streams(monkeypatch):
    monkeypatch.setattr(settings, "max_pdf_decompressed_bytes", 1024 * 1024)
    with pytest.raises(parser.DecompressionLimitError):
        parser.extract_text_from_pdf(make_pdf([b" " * 600000, b" " * 600000]))


def test_pdf_text_limit_applies_during_extraction(monkeypatch):
    monkeypatch.setattr(parser, "MAX_EXTRACTED_CHARS", 10)
    with pytest.raises(parser.DecompressionLimitError):
        parser.parse_resume_bytes(make_pdf([b"BT /F1 12 Tf (This sentence exceeds ten characters) Tj ET"]), "resume.pdf")


def test_normal_pdf_is_read():
    assert "Hello" in parser.parse_resume_bytes(make_pdf([b"BT /F1 12 Tf (Hello) Tj ET"]), "resume.pdf")


def test_missing_pdf_dependency_never_falls_back_to_document_bytes(monkeypatch):
    original = builtins.__import__

    def missing_pdfminer(name, *args, **kwargs):
        if name == "pdfminer.high_level":
            raise ModuleNotFoundError("Synthetic missing pdfminer")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_pdfminer)
    with pytest.raises(parser.ParserDependencyError):
        parser.parse_resume_bytes(make_pdf([b"BT /F1 12 Tf (Hello) Tj ET"]), "resume.pdf")


def test_parser_dependency_error_survives_worker_transport_and_worker_recovers():
    with pytest.raises(parser.ParserDependencyError):
        parser.run_parser_in_process_with_timeout(b"test", "resume.pdf", custom_fn=missing_parser_dependency)
    assert parser.run_parser_in_process_with_timeout(b"ordinary resume", "resume.pdf") == "ordinary resume"


def test_upload_returns_safe_503_when_parser_dependency_is_unavailable(monkeypatch):
    monkeypatch.setattr(resumes, "parse_resume_bytes_async", AsyncMock(side_effect=parser.ParserDependencyError("private failure")))
    save = MagicMock()
    monkeypatch.setattr(resumes.store, "add_resume", save)
    response = TestClient(app).post("/api/resumes", files={"file": ("resume.pdf", b"%PDF test", "application/pdf")})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "private failure" not in response.text
    save.assert_not_called()


def test_os_memory_limit_stops_allocation_and_worker_recovers(monkeypatch):
    monkeypatch.setattr(settings, "parser_memory_limit_mb", 128)
    with pytest.raises(parser.DecompressionLimitError):
        parser.run_parser_in_process_with_timeout(b"test", "resume.pdf", custom_fn=allocate_too_much)
    assert parser.run_parser_in_process_with_timeout(b"ordinary resume", "resume.pdf") == "ordinary resume"


def test_unsupported_memory_isolation_fails_closed(monkeypatch):
    monkeypatch.setattr("engine.normalize.memory_limit.os", type("OS", (), {"name": "unsupported"}))
    with pytest.raises(RuntimeError, match="unsupported"):
        limit_process_memory(128)
