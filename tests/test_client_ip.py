"""Phase 4 — Secure Client IP Handling and Proxy Trust Tests.

Covers:
1. Spoofed forwarding headers from untrusted peers (ignored; connection peer used).
2. Legitimate single-hop and multi-hop trusted proxy chains (right-to-left traversal).
3. Attacker-injected X-Forwarded-For prefix behind a trusted proxy.
4. Malformed header values, out-of-range IPs, ports, and empty entries.
5. IPv6 addresses for both clients and trusted proxies (including normalization).
6. Missing headers and missing request.client fallback.
7. Multiple X-Forwarded-For header instances.
8. Salted SHA-256 IP hashing and zero raw IP logging.
9. End-to-end guest quota enforcement against X-Forwarded-For spoofing.
"""

from __future__ import annotations

import hashlib
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from api.auth import _parse_trusted_proxy_networks, get_client_ip, hash_guest_ip
from api.config import settings
from api.main import app
from api.store import store


def _make_request(
    peer_ip: str | None = "198.51.100.10",
    headers: list[tuple[bytes, bytes]] | dict[str, str] | None = None,
) -> Request:
    """Build a minimal Starlette Request with an explicit socket peer and headers."""
    raw_headers: list[tuple[bytes, bytes]] = []
    if isinstance(headers, dict):
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))
    elif isinstance(headers, list):
        raw_headers = headers

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "headers": raw_headers,
        "client": (peer_ip, 54321) if peer_ip is not None else None,
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clear_proxy_cache() -> None:
    _parse_trusted_proxy_networks.cache_clear()


# ── 1. Spoofed headers from untrusted peers ──────────────────────────────────


def test_untrusted_peer_spoofed_header_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TRUSTED_PROXIES is empty, X-Forwarded-For is ignored and connection peer is used."""
    monkeypatch.setattr(settings, "trusted_proxies", "")
    req = _make_request(
        peer_ip="198.51.100.25",
        headers={"X-Forwarded-For": "203.0.113.195"},
    )
    assert get_client_ip(req) == "198.51.100.25"


def test_untrusted_peer_not_in_configured_proxies_ignores_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When TRUSTED_PROXIES is configured, a peer outside that range cannot spoof XFF."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8,127.0.0.1")
    req = _make_request(
        peer_ip="198.51.100.99",
        headers={"X-Forwarded-For": "1.1.1.1, 8.8.8.8, 10.0.0.1"},
    )
    assert get_client_ip(req) == "198.51.100.99"


# ── 2. Legitimate trusted proxy chains ───────────────────────────────────────


def test_trusted_single_hop_proxy_extracts_client_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single trusted proxy forwards the direct client IP."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1")
    req = _make_request(
        peer_ip="10.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.42"},
    )
    assert get_client_ip(req) == "203.0.113.42"


def test_trusted_multi_hop_proxy_chain_walks_right_to_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Right-to-left traversal skips trusted intermediate proxies and stops at first untrusted IP."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8, 172.16.0.0/12")
    req = _make_request(
        peer_ip="10.0.0.5",
        headers={"X-Forwarded-For": "203.0.113.50, 172.16.4.2, 10.0.1.9"},
    )
    assert get_client_ip(req) == "203.0.113.50"


def test_spoofed_prefix_behind_trusted_proxy_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If an attacker sends X-Forwarded-For: 1.2.3.4 to a trusted proxy, the proxy appends
    the attacker's real IP (198.51.100.77). Right-to-left parsing must return 198.51.100.77,
    never the attacker-controlled 1.2.3.4.
    """
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(
        peer_ip="10.0.0.1",
        headers={"X-Forwarded-For": "1.2.3.4, 198.51.100.77, 10.0.0.2"},
    )
    assert get_client_ip(req) == "198.51.100.77"


def test_all_hops_trusted_returns_leftmost_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If every hop in X-Forwarded-For is a trusted proxy, return the leftmost hop."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(
        peer_ip="10.0.0.1",
        headers={"X-Forwarded-For": "10.0.0.3, 10.0.0.2"},
    )
    assert get_client_ip(req) == "10.0.0.3"


def test_multiple_x_forwarded_for_headers_combined_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple X-Forwarded-For headers are concatenated in order per RFC 7230 and parsed right-to-left."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(
        peer_ip="10.0.0.1",
        headers=[
            (b"x-forwarded-for", b"1.1.1.1, 203.0.113.88"),
            (b"x-forwarded-for", b"10.0.0.2"),
        ],
    )
    assert get_client_ip(req) == "203.0.113.88"


# ── 3. Malformed values ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "malformed_xff",
    [
        "not-an-ip",
        "999.999.999.999",
        "203.0.113.1:8080",
        "[2001:db8::1]:443",
        "<script>alert(1)</script>",
        "127.0.0.1; DROP TABLE analyses;",
        "203.0.113.5, invalid-hop",
        "invalid-hop, 10.0.0.2",
        "203.0.113.5, ",
        ", 10.0.0.2",
        " , , ",
    ],
)
def test_malformed_x_forwarded_for_falls_back_to_peer(
    monkeypatch: pytest.MonkeyPatch,
    malformed_xff: str,
) -> None:
    """Any malformed IP in the trusted forwarding chain causes fallback to the connection peer."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(
        peer_ip="10.0.0.1",
        headers={"X-Forwarded-For": malformed_xff},
    )
    assert get_client_ip(req) == "10.0.0.1"


def test_attacker_cannot_poison_xff_with_malformed_prefix_behind_trusted_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If an attacker (198.51.100.77) sends a malformed X-Forwarded-For prefix to a
    trusted proxy (10.0.0.1), the proxy appends 198.51.100.77 on the right.
    Right-to-left traversal must still identify 198.51.100.77 and not fall back to 10.0.0.1.
    """
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(
        peer_ip="10.0.0.1",
        headers={"X-Forwarded-For": "malformed-garbage, , 198.51.100.77"},
    )
    assert get_client_ip(req) == "198.51.100.77"


def test_invalid_trusted_proxies_config_entry_is_ignored_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid entries in TRUSTED_PROXIES are skipped without crashing."""
    monkeypatch.setattr(settings, "trusted_proxies", "not-a-cidr, 10.0.0.1")
    req = _make_request(
        peer_ip="10.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert get_client_ip(req) == "203.0.113.9"


# ── 4. IPv6 support ──────────────────────────────────────────────────────────


def test_ipv6_client_behind_trusted_ipv4_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IPv6 client address is parsed and normalized correctly."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(
        peer_ip="10.0.0.1",
        headers={"X-Forwarded-For": "2001:0db8:85a3:0000:0000:8a2e:0370:7334"},
    )
    assert get_client_ip(req) == "2001:db8:85a3::8a2e:370:7334"


def test_ipv6_trusted_proxy_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """IPv6 trusted proxy peer and intermediate hop resolve client IP accurately."""
    monkeypatch.setattr(settings, "trusted_proxies", "::1/128, 2001:db8:1::/48")
    req = _make_request(
        peer_ip="::1",
        headers={"X-Forwarded-For": "2001:db8:99::42, 2001:db8:1::5"},
    )
    assert get_client_ip(req) == "2001:db8:99::42"


def test_untrusted_ipv6_peer_cannot_spoof_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Untrusted IPv6 connection peer ignores X-Forwarded-For and returns normalized peer IPv6."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8, ::1/128")
    req = _make_request(
        peer_ip="2001:0db8:0000:0000:0000:0000:dead:beef",
        headers={"X-Forwarded-For": "1.1.1.1"},
    )
    assert get_client_ip(req) == "2001:db8::dead:beef"


# ── 5. Missing headers and missing peer fallback ─────────────────────────────


def test_missing_headers_from_untrusted_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(peer_ip="198.51.100.12", headers={})
    assert get_client_ip(req) == "198.51.100.12"


def test_missing_headers_from_trusted_proxy_returns_proxy_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(peer_ip="10.0.0.1", headers={})
    assert get_client_ip(req) == "10.0.0.1"


def test_empty_header_from_trusted_proxy_returns_proxy_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(peer_ip="10.0.0.1", headers={"X-Forwarded-For": "   "})
    assert get_client_ip(req) == "10.0.0.1"


def test_missing_request_client_defaults_to_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    req = _make_request(peer_ip=None, headers={"X-Forwarded-For": "203.0.113.1"})
    assert get_client_ip(req) == "127.0.0.1"


# ── 6. Salted IP hashing & zero raw IP logging ──────────────────────────────


def test_hash_guest_ip_uses_salted_sha256_and_never_logs_raw_ip(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1")
    monkeypatch.setattr(settings, "guest_ip_salt", "test-secret-salt-99")

    raw_client_ip = "203.0.113.111"
    req = _make_request(
        peer_ip="10.0.0.1",
        headers={"X-Forwarded-For": raw_client_ip},
    )

    with caplog.at_level(logging.DEBUG):
        digest = hash_guest_ip(req)

    expected = hashlib.sha256(f"test-secret-salt-99:{raw_client_ip}".encode()).hexdigest()
    assert digest == expected
    assert raw_client_ip not in digest
    assert raw_client_ip not in caplog.text


# ── 7. End-to-End Guest Quota Protection Against Spoofing ───────────────────


def test_untrusted_peer_cannot_bypass_guest_quota_by_rotating_x_forwarded_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attacker connecting from an untrusted IP cannot bypass the 1-per-day
    guest analysis quota by rotating spoofed X-Forwarded-For headers.
    """
    monkeypatch.setattr(settings, "enforce_guest_limit", True)
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    monkeypatch.setattr(settings, "guest_ip_salt", "quota-spoof-test-salt")
    store.guest_ip_usage.clear()

    untrusted_client = TestClient(app, client=("198.51.100.200", 50000))

    res_id = untrusted_client.post(
        "/api/resumes",
        files={"file": ("guest.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = untrusted_client.post("/api/jobs", json={"text": "x" * 45}).json()["job_id"]

    # First guest analysis with spoofed header #1 succeeds (bound to peer 198.51.100.200)
    first = untrusted_client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers={"X-Forwarded-For": "203.0.113.1"},
    )
    assert first.status_code == 202

    # Second guest analysis with a DIFFERENT spoofed header #2 MUST be blocked (429)
    second = untrusted_client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers={"X-Forwarded-For": "203.0.113.2"},
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "GUEST_LIMIT_REACHED"


def test_distinct_clients_behind_trusted_proxy_have_independent_guest_quotas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When requests arrive from a configured trusted proxy, distinct client IPs
    in X-Forwarded-For get separate guest quota identities, while a client spoofing
    an extra leftmost IP is still rate-limited on their real IP.
    """
    monkeypatch.setattr(settings, "enforce_guest_limit", True)
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1")
    monkeypatch.setattr(settings, "guest_ip_salt", "trusted-proxy-quota-salt")
    store.guest_ip_usage.clear()

    proxy_client = TestClient(app, client=("10.0.0.1", 50000))

    res_id = proxy_client.post(
        "/api/resumes",
        files={"file": ("guest.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = proxy_client.post("/api/jobs", json={"text": "x" * 45}).json()["job_id"]

    # Client A (203.0.113.10) succeeds
    res_a1 = proxy_client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert res_a1.status_code == 202

    # Client A tries to spoof a leftmost IP (1.2.3.4, 203.0.113.10) -> still blocked!
    res_a2 = proxy_client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.10"},
    )
    assert res_a2.status_code == 429
    assert res_a2.json()["error"]["code"] == "GUEST_LIMIT_REACHED"

    # Client B (203.0.113.20) behind the same trusted proxy succeeds
    res_b1 = proxy_client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers={"X-Forwarded-For": "203.0.113.20"},
    )
    assert res_b1.status_code == 202
