"""Bound real work after caller timeouts, including slow-drip HTTP responses."""

import http.server
import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from httpcore._backends.sync import SyncStream

from api.config import settings
from api.main import app
from api.routes import analyses
from api.store import store
from engine.execution import BoundedWorkPool, WorkCapacityError, WorkTimeoutError, deadline_scope
from engine.ingest import url_safety
from engine.rewrite import llm


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.005)


def test_timed_out_work_keeps_capacity_until_it_really_stops():
    pool = BoundedWorkPool("test-capacity")
    release = threading.Event()
    entered = threading.Event()

    def blocked():
        entered.set()
        release.wait(timeout=2)

    try:
        with pytest.raises(WorkTimeoutError):
            pool.run(blocked, timeout=0.03, limit=1)
        assert entered.is_set() and pool.active == 1
        with pytest.raises(WorkCapacityError):
            pool.run(lambda: None, timeout=0.1, limit=1)
    finally:
        release.set()
    wait_until(lambda: pool.active == 0)
    assert pool.run(lambda: "recovered", timeout=1, limit=1) == "recovered"


def test_slow_drip_http_hits_overall_deadline_and_closes_socket(monkeypatch):
    completed = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "192")
            self.end_headers()
            try:
                for _ in range(12):
                    time.sleep(0.04)
                    self.wfile.write(b"x" * 16)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                completed.set()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.5
    worker = threading.Thread(target=server.handle_request, daemon=True)
    worker.start()
    # Only the connection destination is replaced with our own synthetic server.
    # Exercise the production deadline stream around a real socket.
    def connect(self, host, port, **kwargs):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", server.server_port))
        return url_safety._DeadlineStream(SyncStream(sock))

    monkeypatch.setattr(url_safety._PinnedNetworkBackend, "connect_tcp", connect)
    transport, backend = url_safety.build_pinned_transport({})
    monkeypatch.setattr(url_safety, "build_pinned_transport", lambda pins: (transport, backend))
    monkeypatch.setattr(url_safety, "validate_and_resolve_url", lambda url: url_safety.ValidatedUrl(url, "http", "public.example", 80, ("93.184.216.34",)))
    pool = BoundedWorkPool("test-drip")
    monkeypatch.setattr(url_safety, "_fetch_pool", pool)
    monkeypatch.setattr(settings, "fetch_timeout_seconds", 0.15)
    try:
        start = time.monotonic()
        with pytest.raises((WorkTimeoutError, httpx.TimeoutException)):
            url_safety.safe_http_get("http://public.example/job", timeout=0.15)
        assert time.monotonic() - start < 0.4
        wait_until(lambda: pool.active == 0)
        assert completed.wait(timeout=1)
    finally:
        server.server_close()
        worker.join(timeout=1)


def test_redirects_share_one_budget(monkeypatch):
    def handler(request):
        time.sleep(0.03)
        return httpx.Response(302, headers={"Location": "/next"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(url_safety, "build_pinned_transport", lambda pins: (transport, None))
    monkeypatch.setattr(url_safety, "validate_and_resolve_url", lambda url: url_safety.ValidatedUrl(url, "http", "public.example", 80, ("93.184.216.34",)))
    pool = BoundedWorkPool("test-redirects")
    monkeypatch.setattr(url_safety, "_fetch_pool", pool)
    monkeypatch.setattr(settings, "fetch_timeout_seconds", 0.05)
    with pytest.raises(WorkTimeoutError):
        url_safety.safe_http_get("http://public.example/start", timeout=0.05)
    wait_until(lambda: pool.active == 0)


def test_fetch_endpoint_rejects_overload_and_never_caches_late_results(monkeypatch):
    release = threading.Event()
    pool = BoundedWorkPool("test-fetch-route")
    monkeypatch.setattr(url_safety, "_fetch_pool", pool)
    monkeypatch.setattr(settings, "fetch_timeout_seconds", 0.03)
    monkeypatch.setattr(settings, "max_concurrent_fetches", 1)

    def scrape(url):
        release.wait(timeout=2)
        return "Synthetic job text long enough for normal processing."

    cache = MagicMock()
    monkeypatch.setattr("engine.ingest.scraper.scrape_job_url", scrape)
    monkeypatch.setattr("engine.ingest.cache.save_cached_text", cache)
    try:
        with TestClient(app) as client:
            response = client.post("/api/jobs/fetch-url", json={"url": "https://public.example/job"})
            assert response.status_code == 504
            assert pool.active == 1
            assert client.post("/api/jobs/fetch-url", json={"url": "https://public.example/job"}).status_code == 429
    finally:
        release.set()
    wait_until(lambda: pool.active == 0)
    cache.assert_not_called()


def test_rewrite_timeout_keeps_capacity_and_drops_late_results(monkeypatch):
    release = threading.Event()
    pool = BoundedWorkPool("test-rewrite-route")
    monkeypatch.setattr(analyses, "_rewrite_pool", pool)
    monkeypatch.setattr(settings, "rewrite_timeout_seconds", 0.04)
    monkeypatch.setattr(settings, "max_concurrent_rewrites", 1)
    records = [store.create_analysis("synthetic-r", "synthetic-j", "KH") for _ in range(2)]
    for record in records:
        record.status = "done"
        record.match = store.pick_fixture("synthetic-j")

    def detect(*args):
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(analyses, "detect_hidden_strengths", detect)
    try:
        with TestClient(app) as client:
            assert client.post(f"/api/analyses/{records[0].id}/rewrites").status_code == 504
            assert pool.active == 1
            assert records[0].rewrite_in_progress
            assert client.post(f"/api/analyses/{records[1].id}/rewrites").status_code == 429
    finally:
        release.set()
    wait_until(lambda: pool.active == 0)
    assert not records[0].rewrite_in_progress
    assert records[0].rewrite_status is None
    with TestClient(app) as client:
        assert client.post(f"/api/analyses/{records[1].id}/rewrites").status_code == 200


def test_rewrite_sdk_receives_remaining_workflow_budget(monkeypatch):
    captured = []
    response = SimpleNamespace(text='{"ok":true}', candidates=[])

    def generate(**kwargs):
        captured.append(kwargs["config"].http_options)
        return response

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    with deadline_scope(0.2):
        llm.call_structured(system="s", user="u", tool_name="t", tool_description="d", tool_schema={"type": "object"})
    assert 0 < captured[0].timeout <= 200
    assert captured[0].retry_options.attempts == 1
