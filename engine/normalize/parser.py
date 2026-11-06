"""Raw text parsers for resume ingestion (.pdf, .docx, and raw text).

OWNER: Person A (Dy David)
Phase 3 hardening:
- Bounds DOCX decompressed size, entry count, compression ratio, and actual
  decompressed stream bytes (defending against both header and stream zip bombs).
- Bounds PDF page count and extracted character count.
- Executes parsing in a supervised child process (`spawn` context) with a hard
  timeout that terminates/kills the worker process on timeout so CPU and memory
  work genuinely stops.
- Bounds concurrent parsing via semaphore and offloads work from the async event loop.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import io
import logging
import multiprocessing as mp
import threading
import time
import zipfile
from collections.abc import Callable
from multiprocessing.connection import Connection

from engine.normalize.pdf_limits import PDFResourceLimitError, pdf_decode_budget

logger = logging.getLogger(__name__)

DEFAULT_MAX_DOCX_DECOMPRESSED_BYTES = 10 * 1024 * 1024  # 10 MB total decompressed
MAX_DOCX_MEMBER_BYTES = 5 * 1024 * 1024  # 5 MB single member
MAX_DOCX_FILE_COUNT = 500
MAX_DOCX_COMPRESSION_RATIO = 100.0
MAX_PDF_PAGES = 15
MAX_EXTRACTED_CHARS = 200_000
DEFAULT_PARSER_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_CONCURRENT_PARSES = 3
DEFAULT_CONCURRENCY_ACQUIRE_TIMEOUT = 1.0
MAX_JOBS_PER_WORKER_PROCESS = 50


class DecompressionLimitError(ValueError):
    """Raised when a compressed document (e.g. DOCX/ZIP) violates decompression bounds."""


class ParserDependencyError(RuntimeError):
    """A required parser is unavailable; never treat document bytes as extracted text."""


class ParserTimeoutError(TimeoutError):
    """Raised when document parsing exceeds the time limit and the worker process is killed."""

    def __init__(self, message: str, *, pid: int | None = None) -> None:
        super().__init__(message)
        self.pid = pid


class ParserConcurrencyError(RuntimeError):
    """Raised when maximum concurrent document parses are already in flight."""


def _get_max_docx_decompressed_bytes(override: int | None = None) -> int:
    if override is not None:
        return override
    try:
        from api.config import settings

        return int(settings.max_docx_decompressed_bytes)
    except Exception:
        return DEFAULT_MAX_DOCX_DECOMPRESSED_BYTES


def _get_parser_timeout_seconds(override: float | None = None) -> float:
    if override is not None:
        return override
    try:
        from api.config import settings

        return float(settings.parser_timeout_seconds)
    except Exception:
        return DEFAULT_PARSER_TIMEOUT_SECONDS


def _get_max_concurrent_parses(override: int | None = None) -> int:
    if override is not None:
        return override
    try:
        from api.config import settings

        return max(1, int(settings.max_concurrent_parses))
    except Exception:
        return DEFAULT_MAX_CONCURRENT_PARSES


def validate_docx_zip_safety(
    file_bytes: bytes,
    max_total_bytes: int | None = None,
) -> None:
    """Validate a DOCX (ZIP) archive against zip bombs, forged headers, and oversized entries.

    Checks both the ZIP central directory headers and the actual decompressed
    byte stream before `python-docx` / `lxml` parses the archive.
    """
    limit = _get_max_docx_decompressed_bytes(max_total_bytes)
    member_limit = min(limit, MAX_DOCX_MEMBER_BYTES)

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            infolist = zf.infolist()
            if len(infolist) > MAX_DOCX_FILE_COUNT:
                raise DecompressionLimitError(
                    f"DOCX archive contains too many entries ({len(infolist)} > {MAX_DOCX_FILE_COUNT})."
                )

            header_total = 0
            for info in infolist:
                norm_name = info.filename.replace("\\", "/")
                if norm_name.startswith("/") or ".." in norm_name.split("/"):
                    raise DecompressionLimitError("DOCX archive contains unsafe member path.")

                if info.file_size < 0 or info.file_size > member_limit:
                    raise DecompressionLimitError(
                        f"DOCX member {info.filename!r} uncompressed size ({info.file_size}) "
                        f"exceeds limit ({member_limit} bytes)."
                    )

                header_total += info.file_size
                if header_total > limit:
                    raise DecompressionLimitError(
                        f"DOCX total uncompressed size ({header_total}) exceeds limit ({limit} bytes)."
                    )

                if info.file_size > 1024:
                    ratio = info.file_size / max(info.compress_size, 1)
                    if ratio > MAX_DOCX_COMPRESSION_RATIO:
                        raise DecompressionLimitError(
                            f"DOCX member {info.filename!r} compression ratio ({ratio:.1f}) "
                            f"exceeds safety limit ({MAX_DOCX_COMPRESSION_RATIO})."
                        )

            # Stream-verify actual decompressed bytes to defeat forged ZIP headers
            actual_total = 0
            for info in infolist:
                if info.is_dir():
                    continue
                member_actual = 0
                with zf.open(info, "r") as member_stream:
                    while True:
                        chunk = member_stream.read(16384)
                        if not chunk:
                            break
                        chunk_len = len(chunk)
                        member_actual += chunk_len
                        actual_total += chunk_len
                        if member_actual > member_limit:
                            raise DecompressionLimitError(
                                f"DOCX member {info.filename!r} decompressed stream exceeded "
                                f"limit ({member_limit} bytes)."
                            )
                        if actual_total > limit:
                            raise DecompressionLimitError(
                                f"DOCX decompressed stream exceeded total limit ({limit} bytes)."
                            )
    except DecompressionLimitError:
        raise
    except zipfile.BadZipFile as err:
        raise ValueError(f"Invalid DOCX zip archive: {err}") from err
    except Exception as err:
        raise ValueError(f"Could not validate DOCX archive: {err}") from err


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from PDF file bytes using pdfminer.six with page and size bounds."""
    try:
        from pdfminer.high_level import extract_text_to_fp

        from api.config import settings

        class BoundedText(io.StringIO):
            def write(self, value):
                if self.tell() + len(value) > MAX_EXTRACTED_CHARS:
                    raise PDFResourceLimitError("PDF text limit exceeded")
                return super().write(value)

        output = BoundedText()
        with pdf_decode_budget(settings.max_pdf_decompressed_bytes):
            extract_text_to_fp(io.BytesIO(file_bytes), output, maxpages=MAX_PDF_PAGES, codec=None)
        text = output.getvalue()
        if not text:
            return ""
        cleaned = text.strip()
        if len(cleaned) > MAX_EXTRACTED_CHARS:
            cleaned = cleaned[:MAX_EXTRACTED_CHARS]
        return cleaned
    except (PDFResourceLimitError, MemoryError) as err:
        raise DecompressionLimitError("PDF resource limit exceeded") from err
    except ImportError as err:
        raise ParserDependencyError("PDF parsing is unavailable. Install the parse dependencies.") from err
    except Exception as err:
        logger.error("Failed to parse PDF file: %s", err)
        raise ValueError(f"Could not extract text from PDF: {err}") from err


def extract_text_from_docx(
    file_bytes: bytes,
    *,
    max_decompressed_bytes: int | None = None,
) -> str:
    """Extract plain text from DOCX file bytes using python-docx after zip-bomb validation."""
    validate_docx_zip_safety(file_bytes, max_total_bytes=max_decompressed_bytes)
    try:
        import docx

        doc = docx.Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(
                    cell.text.strip() for cell in row.cells if cell.text.strip()
                )
                if row_text:
                    paragraphs.append(row_text)
        joined = "\n".join(paragraphs).strip()
        if len(joined) > MAX_EXTRACTED_CHARS:
            joined = joined[:MAX_EXTRACTED_CHARS]
        return joined
    except DecompressionLimitError:
        raise
    except ModuleNotFoundError as err:
        # Fallback to standard library XML extraction when python-docx is not installed
        try:
            import xml.etree.ElementTree as ET

            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                if "word/document.xml" in zf.namelist():
                    xml_content = zf.read("word/document.xml")
                    tree = ET.fromstring(xml_content)
                    texts = [
                        elem.text
                        for elem in tree.iter()
                        if elem.text and elem.text.strip()
                    ]
                    joined = "\n".join(texts).strip()
                    if len(joined) > MAX_EXTRACTED_CHARS:
                        joined = joined[:MAX_EXTRACTED_CHARS]
                    return joined
        except Exception as inner_err:
            raise ValueError(f"Could not extract text from DOCX: {inner_err}") from inner_err
        raise ValueError("Could not extract text from DOCX: python-docx not installed") from err
    except Exception as err:
        logger.error("Failed to parse DOCX file: %s", err)
        raise ValueError(f"Could not extract text from DOCX: {err}") from err


def parse_resume_bytes(
    file_bytes: bytes,
    filename: str,
    *,
    max_docx_decompressed_bytes: int | None = None,
) -> str:
    """Route resume file bytes to the appropriate parser based on extension or magic bytes."""
    if not file_bytes:
        raise ValueError("Resume file is empty")

    ext = filename.lower().strip().split(".")[-1] if "." in filename else ""
    is_pk_zip = file_bytes.startswith(b"PK\x03\x04")
    is_pdf_magic = file_bytes.startswith(b"%PDF")

    raw_text = ""

    # 1. Magic byte check for DOCX (zip file starting with PK)
    if is_pk_zip or ext in ("docx", "doc"):
        try:
            raw_text = extract_text_from_docx(
                file_bytes,
                max_decompressed_bytes=max_docx_decompressed_bytes,
            )
        except DecompressionLimitError:
            # Never fall back to raw UTF-8 decoding when a zip bomb / decompression limit is hit
            raise
        except Exception as err:
            if is_pk_zip:
                raise ValueError(f"DOCX parser failed on archive: {err}") from err
            logger.warning("DOCX parser failed: %s. Trying fallback text decoder.", err)

    # 2. Magic byte check for PDF
    if not raw_text and (is_pdf_magic or ext == "pdf"):
        try:
            raw_text = extract_text_from_pdf(file_bytes)
        except (DecompressionLimitError, ParserDependencyError):
            raise
        except Exception as err:
            logger.warning("PDF parser failed: %s. Trying fallback text decoder.", err)

    # 3. Text decoding fallback (only for non-zip inputs such as plain text or synthetic test stubs)
    if not raw_text and not is_pk_zip:
        try:
            raw_text = file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            raw_text = file_bytes.decode("utf-8", errors="ignore").strip()

    if len(raw_text) > MAX_EXTRACTED_CHARS:
        raw_text = raw_text[:MAX_EXTRACTED_CHARS]

    if not raw_text or not raw_text.strip():
        raise ValueError("Resume file yielded no extractable text")

    return raw_text


# ── Process-Isolated Supervised Execution ───────────────────────────────────


def _parser_worker_loop(child_conn: Connection, memory_mb: int) -> None:
    """Long-lived worker loop inside a spawned child process."""
    from engine.normalize.memory_limit import limit_process_memory

    try:
        memory_handle = limit_process_memory(memory_mb)
        child_conn.send(("ready", None))
    except Exception:
        child_conn.send(("startup_error", None))
        child_conn.close()
        return
    jobs_processed = 0
    while True:
        try:
            if not child_conn.poll(timeout=120.0):
                break
            payload = child_conn.recv()
        except (EOFError, OSError):
            break

        if payload is None:
            break

        file_bytes, filename, max_docx_bytes, custom_fn = payload
        try:
            if custom_fn is not None:
                result = custom_fn(file_bytes, filename)
            else:
                result = parse_resume_bytes(
                    file_bytes,
                    filename,
                    max_docx_decompressed_bytes=max_docx_bytes,
                )
            child_conn.send(("ok", result))
        except ParserDependencyError:
            child_conn.send(("dependency_err", "Document parsing service unavailable."))
        except (DecompressionLimitError, MemoryError) as err:
            child_conn.send(("decomp_err", str(err)))
        except BaseException as err:
            child_conn.send(("err", f"{type(err).__name__}: {err}"))

        jobs_processed += 1
        if jobs_processed >= MAX_JOBS_PER_WORKER_PROCESS:
            break

    with contextlib.suppress(Exception):
        child_conn.close()
    del memory_handle  # Keep the OS handle alive for the entire worker lifetime.


class _SupervisedParserWorker:
    """Manages a single spawned child process for document parsing."""

    def __init__(self) -> None:
        self._ctx = mp.get_context("spawn")
        self._proc: mp.Process | None = None
        self._parent_conn: Connection | None = None
        self._jobs_run = 0
        self._memory_mb: int | None = None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def _ensure_started(self) -> None:
        from api.config import settings

        if (
            self._proc is not None
            and self._proc.is_alive()
            and self._parent_conn is not None
            and self._jobs_run < MAX_JOBS_PER_WORKER_PROCESS
            and self._memory_mb == settings.parser_memory_limit_mb
        ):
            return
        self.kill()
        parent_conn, child_conn = self._ctx.Pipe(duplex=True)
        proc = self._ctx.Process(
            target=_parser_worker_loop,
            args=(child_conn, settings.parser_memory_limit_mb),
            daemon=True,
        )
        proc.start()
        child_conn.close()
        self._proc = proc
        self._parent_conn = parent_conn
        self._jobs_run = 0
        self._memory_mb = settings.parser_memory_limit_mb
        if not parent_conn.poll(settings.parser_startup_timeout_seconds):
            self.kill()
            raise ParserTimeoutError("Parser worker startup timed out")
        try:
            status, _ = parent_conn.recv()
        except (EOFError, OSError):
            status = "startup_error"
        if status != "ready":
            self.kill()
            raise DecompressionLimitError("Parser memory isolation is unavailable")

    def kill(self) -> int | None:
        """Forcefully terminate and reap the child process, returning its former PID."""
        killed_pid = self._proc.pid if self._proc is not None else None
        if self._parent_conn is not None:
            with contextlib.suppress(Exception):
                self._parent_conn.close()
            self._parent_conn = None

        if self._proc is not None:
            try:
                if self._proc.is_alive():
                    self._proc.terminate()
                    self._proc.join(timeout=0.5)
                if self._proc.is_alive():
                    self._proc.kill()
                    self._proc.join(timeout=0.5)
            except Exception:
                pass
            self._proc = None
        self._jobs_run = 0
        return killed_pid

    def execute(
        self,
        file_bytes: bytes,
        filename: str,
        *,
        timeout_seconds: float,
        max_docx_bytes: int,
        custom_fn: Callable[[bytes, str], str] | None = None,
    ) -> str:
        self._ensure_started()
        assert self._parent_conn is not None
        assert self._proc is not None

        try:
            self._parent_conn.send((file_bytes, filename, max_docx_bytes, custom_fn))
            self._jobs_run += 1

            if not self._parent_conn.poll(timeout=timeout_seconds):
                killed_pid = self.kill()
                raise ParserTimeoutError(
                    f"Document parsing timed out after {timeout_seconds:.2f}s "
                    f"(terminated worker pid={killed_pid}).",
                    pid=killed_pid,
                )

            status, value = self._parent_conn.recv()
        except ParserTimeoutError:
            raise
        except (EOFError, OSError, BrokenPipeError) as err:
            killed_pid = self.kill()
            raise ValueError(
                f"Parser worker process terminated unexpectedly (pid={killed_pid}): {err}"
            ) from err

        if status == "ok":
            return str(value)
        if status == "decomp_err":
            self.kill()
            raise DecompressionLimitError(str(value))
        if status == "dependency_err":
            self.kill()
            raise ParserDependencyError(str(value))
        raise ValueError(str(value))


class _ParserSupervisor:
    """Bounds concurrent document parsing and manages a pool of supervised child processes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idle_workers: list[_SupervisedParserWorker] = []
        self._active_count = 0
        self._cond = threading.Condition(self._lock)

    def acquire_worker(self, max_concurrency: int, wait_timeout: float) -> _SupervisedParserWorker:
        deadline = time.monotonic() + max(0.0, wait_timeout)
        with self._cond:
            while self._active_count >= max_concurrency:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ParserConcurrencyError(
                        f"Maximum concurrent document parses ({max_concurrency}) exceeded."
                    )
                self._cond.wait(timeout=remaining)

            self._active_count += 1
            if self._idle_workers:
                return self._idle_workers.pop()
            return _SupervisedParserWorker()

    def release_worker(self, worker: _SupervisedParserWorker, max_concurrency: int) -> None:
        with self._cond:
            self._active_count = max(0, self._active_count - 1)
            if worker.is_alive() and len(self._idle_workers) < max_concurrency:
                self._idle_workers.append(worker)
            else:
                worker.kill()
            self._cond.notify()

    def shutdown_all(self) -> None:
        with self._cond:
            while self._idle_workers:
                w = self._idle_workers.pop()
                w.kill()


_supervisor = _ParserSupervisor()
atexit.register(_supervisor.shutdown_all)


def run_parser_in_process_with_timeout(
    file_bytes: bytes,
    filename: str,
    *,
    timeout_seconds: float | None = None,
    max_docx_decompressed_bytes: int | None = None,
    max_concurrency: int | None = None,
    acquire_timeout: float = DEFAULT_CONCURRENCY_ACQUIRE_TIMEOUT,
    custom_fn: Callable[[bytes, str], str] | None = None,
) -> str:
    """Parse resume bytes inside a supervised child process with concurrency and timeout bounds.

    If parsing exceeds `timeout_seconds`, the child process is forcefully terminated
    (`terminate()` / `kill()`) so no runaway CPU or memory work continues.
    """
    if not file_bytes:
        raise ValueError("Resume file is empty")

    eff_timeout = _get_parser_timeout_seconds(timeout_seconds)
    eff_docx_max = _get_max_docx_decompressed_bytes(max_docx_decompressed_bytes)
    eff_concurrency = _get_max_concurrent_parses(max_concurrency)

    worker = _supervisor.acquire_worker(eff_concurrency, acquire_timeout)
    try:
        return worker.execute(
            file_bytes,
            filename,
            timeout_seconds=eff_timeout,
            max_docx_bytes=eff_docx_max,
            custom_fn=custom_fn,
        )
    finally:
        _supervisor.release_worker(worker, eff_concurrency)


async def parse_resume_bytes_async(
    file_bytes: bytes,
    filename: str,
    *,
    timeout_seconds: float | None = None,
    max_docx_decompressed_bytes: int | None = None,
    max_concurrency: int | None = None,
    acquire_timeout: float = DEFAULT_CONCURRENCY_ACQUIRE_TIMEOUT,
    custom_fn: Callable[[bytes, str], str] | None = None,
) -> str:
    """Async entrypoint that offloads supervised process parsing from the event loop."""
    return await asyncio.to_thread(
        run_parser_in_process_with_timeout,
        file_bytes,
        filename,
        timeout_seconds=timeout_seconds,
        max_docx_decompressed_bytes=max_docx_decompressed_bytes,
        max_concurrency=max_concurrency,
        acquire_timeout=acquire_timeout,
        custom_fn=custom_fn,
    )
