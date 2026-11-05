"""Regression tests for Phase 1 SSRF protection across URL validation, scrapers, and API routes.

All network and DNS requests are mocked; no real internal services or cloud metadata
endpoints are ever contacted.
"""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from engine.ingest import fetch_jd
from engine.ingest.scraper import is_url_allowed_by_robots, scrape_job_url
from engine.ingest.url_safety import (
    MAX_REDIRECTS,
    UnsafeUrlError,
    _PinnedNetworkBackend,
    build_pinned_transport,
    is_public_ip,
    safe_http_get,
    validate_and_resolve_url,
    validate_url_syntax,
)

client = TestClient(app)


def _addrinfo_ipv4(ip: str, port: int = 443) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]


def _addrinfo_ipv6(ip: str, port: int = 443) -> list[tuple]:
    return [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port, 0, 0))]


# ============================================================================
# 1. Scheme & Embedded Credentials Validation
# ============================================================================


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "ftp://example.com/job.txt",
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/_INFO",
        "javascript:alert(1)",
        "data:text/html,<h1>Job</h1>",
        "ws://example.com/socket",
        "wss://example.com/socket",
        "http://user:password@example.com/job",
        "https://admin@example.com/job",
        "https://:secret@example.com/job",
        "https://jobnet.com.kh@127.0.0.1/job/123",
        "https://www.camhr.com@169.254.169.254/a/job/10672005",
        "http:///path-only",
        "https://example.com:99999/job",
        "https://example.com/job with spaces",
    ],
)
def test_rejects_disallowed_schemes_and_embedded_credentials(unsafe_url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url_syntax(unsafe_url)


# ============================================================================
# 2. Non-Public IPv4 & IPv6 Address Blocking
# ============================================================================


@pytest.mark.parametrize(
    "non_public_ip",
    [
        # Loopback IPv4
        "127.0.0.1",
        "127.0.0.53",
        "127.255.255.254",
        # Private RFC 1918 IPv4
        "10.0.0.1",
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.254",
        "192.168.0.1",
        "192.168.1.254",
        # Link-local / Cloud Metadata IPv4
        "169.254.169.254",
        "169.254.0.1",
        # Unspecified IPv4
        "0.0.0.0",
        # CGNAT, Benchmarking, Documentation, Multicast, Reserved, Broadcast IPv4
        "100.64.0.1",
        "100.127.255.254",
        "192.0.0.1",
        "192.0.2.1",
        "198.18.0.1",
        "198.51.100.1",
        "203.0.113.1",
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        # IPv6 Loopback & Unspecified
        "::1",
        "::",
        # IPv6 Link-Local & Unique Local (ULA)
        "fe80::1",
        "fc00::1",
        "fd00::1",
        "fd12:3456:789a::1",
        # IPv6 Multicast, Site-local, Documentation
        "ff02::1",
        "fec0::1",
        "2001:db8::1",
        # IPv4-mapped & 6to4 IPv6 wrapping non-public IPv4
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:192.168.1.1",
        "2002:7f00:0001::1",
    ],
)
def test_is_public_ip_blocks_all_non_public_ipv4_and_ipv6(non_public_ip: str) -> None:
    addr = ipaddress.ip_address(non_public_ip)
    assert is_public_ip(addr) is False


@pytest.mark.parametrize(
    "public_ip",
    [
        "93.184.216.34",
        "8.8.8.8",
        "1.1.1.1",
        "43.106.59.251",
        "2606:2800:220:1:248:1893:25c8:1946",
        "2001:4860:4860::8888",
    ],
)
def test_is_public_ip_allows_global_unicast_ipv4_and_ipv6(public_ip: str) -> None:
    addr = ipaddress.ip_address(public_ip)
    assert is_public_ip(addr) is True


@pytest.mark.parametrize(
    "blocked_url",
    [
        "http://127.0.0.1/job",
        "http://127.0.0.1:8000/api/health",
        "http://localhost/job",
        "http://sub.localhost/job",
        "http://internal.local/job",
        "http://metadata.internal/job",
        "http://10.0.0.1/job",
        "http://172.16.0.1/job",
        "http://192.168.1.1/job",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/job",
        "http://100.64.0.1/job",
        "http://127.1/job",
        "http://0177.0.0.1/job",
        "http://0x7f000001/job",
        "http://2130706433/job",
        "http://[::1]/job",
        "http://[::]:8080/job",
        "http://[fe80::1]/job",
        "http://[fe80::1%25eth0]/job",
        "http://[fc00::1]/job",
        "http://[fd00::1234]/job",
        "http://[::ffff:127.0.0.1]/job",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
    ],
)
def test_validate_and_resolve_url_blocks_private_and_loopback_urls_without_network(
    blocked_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    getaddrinfo_mock = MagicMock(side_effect=AssertionError("Should not query DNS for blocked literal/host"))
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo_mock)

    with pytest.raises(UnsafeUrlError):
        validate_and_resolve_url(blocked_url)

    getaddrinfo_mock.assert_not_called()


# ============================================================================
# 3. Public URLs (IPv4 & IPv6) and Supported Job Boards
# ============================================================================


def test_public_ipv4_and_ipv6_urls_pass_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: _addrinfo_ipv4("93.184.216.34", port))
    v4 = validate_and_resolve_url("https://jobs.example.com/openings/42")
    assert v4.hostname == "jobs.example.com"
    assert v4.port == 443
    assert v4.resolved_ips == ("93.184.216.34",)

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: _addrinfo_ipv6("2606:2800:220:1:248:1893:25c8:1946", port),
    )
    v6 = validate_and_resolve_url("https://ipv6.example.com/jobs/1")
    assert v6.resolved_ips == ("2606:2800:220:1:248:1893:25c8:1946",)


def test_public_job_url_scraping_succeeds_with_mocked_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: _addrinfo_ipv4("93.184.216.34", port))

    html_body = """
    <html>
      <head><title>Backend Engineer at Mekong Tech</title></head>
      <body>
        <h1>Backend Engineer</h1>
        <p>We are seeking a Backend Engineer with 2+ years of Python, FastAPI, and PostgreSQL experience in Phnom Penh.</p>
      </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html_body

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_resp
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    text = scrape_job_url("https://careers.example.com/jobs/backend-engineer")
    assert "Backend Engineer" in text
    assert "Python, FastAPI, and PostgreSQL" in text


# ============================================================================
# 4. Redirect Validation & Redirect Limit Enforcement
# ============================================================================


@pytest.mark.parametrize(
    "redirect_target",
    [
        "http://127.0.0.1:8000/api/health",
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://10.0.0.1/internal",
        "http://192.168.1.1/admin",
        "http://[::1]/private",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
        "http://localhost:3000/",
        "ftp://example.com/file",
        "https://user:pass@example.com/private",
        "https://www.linkedin.com/jobs/view/123",
    ],
)
def test_redirect_to_internal_or_disallowed_target_is_blocked(
    redirect_target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: _addrinfo_ipv4("93.184.216.34", port))

    redirect_resp = MagicMock()
    redirect_resp.status_code = 302
    redirect_resp.headers = {"Location": redirect_target}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [redirect_resp]
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    with pytest.raises(UnsafeUrlError):
        safe_http_get("https://public.example.com/redirect")

    # Only the initial public request was sent; the internal redirect target was never fetched
    assert mock_client.get.call_count == 1


def test_redirect_to_valid_public_url_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: _addrinfo_ipv4("93.184.216.34", port))

    redirect_resp = MagicMock()
    redirect_resp.status_code = 301
    redirect_resp.headers = {"Location": "/careers/final-job"}

    final_resp = MagicMock()
    final_resp.status_code = 200
    final_resp.text = "Final Job Content"

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [redirect_resp, final_resp]
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    resp = safe_http_get("https://public.example.com/shortlink")
    assert resp.text == "Final Job Content"
    assert mock_client.get.call_count == 2
    assert mock_client.get.call_args_list[1].args[0] == "https://public.example.com/careers/final-job"


def test_redirect_limit_exceeded_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: _addrinfo_ipv4("93.184.216.34", port))

    def _make_redirect(step: int) -> MagicMock:
        r = MagicMock()
        r.status_code = 302
        r.headers = {"Location": f"https://public.example.com/hop-{step}"}
        return r

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [_make_redirect(i) for i in range(MAX_REDIRECTS + 2)]
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    with pytest.raises(UnsafeUrlError, match="Maximum redirect limit"):
        safe_http_get("https://public.example.com/start")

    assert mock_client.get.call_count == MAX_REDIRECTS + 1


# ============================================================================
# 5. DNS Rebinding & IP Pinning Protection
# ============================================================================


def test_dns_resolving_to_private_or_mixed_ips_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    # Host resolving to one public IP and one loopback IP must be rejected
    mixed_records = _addrinfo_ipv4("93.184.216.34", 443) + _addrinfo_ipv4("127.0.0.1", 443)
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: mixed_records)

    with pytest.raises(UnsafeUrlError):
        validate_and_resolve_url("https://dual-homed.example.com/job")


def test_dns_rebinding_pinned_backend_connects_only_to_validated_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a DNS rebinding attack where the 1st lookup returns a public IP
    (93.184.216.34) and a 2nd lookup would return 127.0.0.1.

    Verify that:
    1. Only 1 DNS resolution occurs for the hop.
    2. The network backend connects to the pinned public IP ('93.184.216.34'),
       never '127.0.0.1' and never the unvalidated hostname.
    3. TLS verification remains enabled on the transport.
    """
    getaddrinfo_mock = MagicMock(
        side_effect=[
            _addrinfo_ipv4("93.184.216.34", 443),
            _addrinfo_ipv4("127.0.0.1", 443),
        ]
    )
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo_mock)

    validated = validate_and_resolve_url("https://rebind.example.com/job")
    assert validated.resolved_ips == ("93.184.216.34",)
    assert getaddrinfo_mock.call_count == 1

    pinned_map = {(validated.hostname, validated.port): validated.resolved_ips}
    transport, backend = build_pinned_transport(pinned_map)

    fake_sock = MagicMock()
    create_conn_mock = MagicMock(return_value=fake_sock)
    monkeypatch.setattr(socket, "create_connection", create_conn_mock)

    backend.connect_tcp("rebind.example.com", 443, timeout=5.0)

    # DNS was NOT queried a second time during TCP connection establishment
    assert getaddrinfo_mock.call_count == 1
    # Socket connected directly to the pinned public IP, not the rebound 127.0.0.1 or hostname
    create_conn_mock.assert_called_once_with(("93.184.216.34", 443), 5.0, source_address=None)
    assert backend.connected_endpoints == [("rebind.example.com", "93.184.216.34", 443)]
    assert transport._pool._ssl_context is not None


def test_dns_rebinding_across_redirect_or_second_fetch_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a host resolves to a public IP on the 1st hop and rebinds to 127.0.0.1
    on a redirect hop (or between job submission and fetch), the 2nd resolution
    is blocked before any connection is made."""
    getaddrinfo_mock = MagicMock(
        side_effect=[
            _addrinfo_ipv4("93.184.216.34", 443),
            _addrinfo_ipv4("127.0.0.1", 443),
        ]
    )
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo_mock)

    redirect_resp = MagicMock()
    redirect_resp.status_code = 302
    redirect_resp.headers = {"Location": "https://rebind.example.com/step2"}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [redirect_resp]
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    with pytest.raises(UnsafeUrlError):
        safe_http_get("https://rebind.example.com/step1")

    assert mock_client.get.call_count == 1


def test_pinned_backend_refuses_tampered_non_public_ip() -> None:
    backend = _PinnedNetworkBackend({("evil.example.com", 80): ("127.0.0.1",)})
    with pytest.raises(UnsafeUrlError):
        backend.connect_tcp("evil.example.com", 80)


# ============================================================================
# 6. Other Ingestion Entrypoints (fetch_jd, is_url_allowed_by_robots)
# ============================================================================


def test_fetch_jd_rejects_unsafe_urls_even_in_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_MODE", "mock")
    with pytest.raises(UnsafeUrlError):
        fetch_jd("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(UnsafeUrlError):
        fetch_jd("http://[::1]:8000/secret")
    with pytest.raises(UnsafeUrlError):
        fetch_jd("https://user:pass@example.com/job")


def test_robots_check_blocks_ssrf_urls() -> None:
    with pytest.raises(UnsafeUrlError):
        is_url_allowed_by_robots("http://127.0.0.1:8000/admin")


# ============================================================================
# 7. FastAPI Route Integration & Error Format Verification
# ============================================================================


@pytest.mark.parametrize(
    "blocked_url",
    [
        "http://127.0.0.1:8000/api/health",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/internal",
        "http://192.168.1.1/router",
        "http://[::1]/loopback",
        "http://[fe80::1]/link-local",
        "http://[fd00::1]/ula",
        "http://[::ffff:127.0.0.1]/mapped",
        "https://user:pass@example.com/job",
        "ftp://example.com/job",
    ],
)
def test_api_submit_job_blocks_unsafe_urls_with_standard_envelope(blocked_url: str) -> None:
    res = client.post("/api/jobs", json={"url": blocked_url})
    assert res.status_code == 422
    body = res.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "JOB_URL_BLOCKED"
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["error_id"].startswith("err_")
    assert "169.254" not in res.text
    assert "127.0.0.1" not in res.text


@pytest.mark.parametrize(
    "blocked_url",
    [
        "http://127.0.0.1:8000/api/health",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/internal",
        "http://172.16.0.1/internal",
        "http://192.168.1.1/router",
        "http://0.0.0.0/",
        "http://[::1]/loopback",
        "http://[fe80::1]/link-local",
        "http://[fc00::1]/ula",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
        "https://user:pass@example.com/job",
        "https://www.jobnet.com.kh@127.0.0.1/job/1",
    ],
)
def test_api_fetch_url_blocks_unsafe_urls_without_leaking_details(blocked_url: str) -> None:
    res = client.post("/api/jobs/fetch-url", json={"url": blocked_url})
    assert res.status_code == 422
    body = res.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "JOB_URL_BLOCKED"
    assert body["error"]["error_id"].startswith("err_")
    assert "169.254" not in res.text
    assert "127.0.0.1" not in res.text


def test_api_fetch_url_blocks_redirect_to_internal_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: _addrinfo_ipv4("93.184.216.34", port))

    redirect_resp = MagicMock()
    redirect_resp.status_code = 302
    redirect_resp.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [redirect_resp]
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    res = client.post("/api/jobs/fetch-url", json={"url": "https://public.example.com/job"})
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "JOB_URL_BLOCKED"
    assert "169.254" not in res.text


def test_api_fetch_url_blocks_dns_rebinding_to_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: _addrinfo_ipv4("10.0.0.42", port))

    res = client.post("/api/jobs/fetch-url", json={"url": "https://rebind.example.com/job"})
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "JOB_URL_BLOCKED"
    assert "10.0.0.42" not in res.text
