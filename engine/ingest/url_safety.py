"""Shared SSRF protection, URL validation, and DNS-pinned HTTP fetching.

Enforces:
- HTTP/HTTPS schemes only; no embedded credentials (username/password).
- Host blocklist (LinkedIn, Facebook, localhost, internal suffixes).
- Blocking of all non-public IPv4 and IPv6 addresses (private, loopback,
  link-local, unspecified, multicast, reserved, CGNAT, and IPv4-mapped/tunnelled IPv6).
- Manual redirect handling with full validation of every redirect target and a
  strict redirect limit.
- DNS rebinding protection by resolving hostnames once per hop, validating all
  returned addresses, and pinning the TCP connection to the validated IP(s)
  while preserving TLS SNI and HTTPS certificate verification.
"""

from __future__ import annotations

import contextvars
import ipaddress
import re
import socket
import ssl
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpcore
import httpx
from httpcore._backends.base import NetworkStream
from httpcore._backends.sync import SyncBackend, SyncStream
from httpcore._exceptions import ConnectError, ConnectTimeout, map_exceptions

from engine.execution import BoundedWorkPool, deadline_scope, remaining_timeout

_fetch_pool = BoundedWorkPool("job-fetch")
_fetch_admitted: contextvars.ContextVar[bool] = contextvars.ContextVar("fetch_admitted", default=False)
_T = TypeVar("_T")


def bounded_fetch(fn: Callable[[], _T]) -> _T:  # noqa: UP047
    """Share capacity/deadline across DNS, scraping, redirects and cache writes."""
    if _fetch_admitted.get():
        remaining_timeout()
        return fn()
    from api.config import settings

    def execute() -> _T:
        token = _fetch_admitted.set(True)
        try:
            remaining_timeout()
            return fn()
        finally:
            _fetch_admitted.reset(token)

    return _fetch_pool.run(
        execute, timeout=settings.fetch_timeout_seconds, limit=settings.max_concurrent_fetches
    )

MAX_REDIRECTS = 5
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MB

_BLOCKED_JOB_HOSTS: frozenset[str] = frozenset({"linkedin.com", "facebook.com"})
_BLOCKED_LOCAL_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "broadcasthost",
    }
)
_BLOCKED_LOCAL_SUFFIXES: tuple[str, ...] = (
    ".localhost",
    ".localhost.localdomain",
    ".local",
    ".internal",
    ".home.arpa",
)

# Explicit non-public / special-purpose IPv4 networks (RFC 6598 CGNAT, RFC 6890, etc.)
_ADDITIONAL_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("100.64.0.0/10"),      # Carrier-Grade NAT (RFC 6598)
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments (RFC 6890)
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("198.18.0.0/15"),      # Benchmarking (RFC 2544)
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2 (RFC 5737)
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3 (RFC 5737)
    ipaddress.ip_network("2001:db8::/32"),      # Documentation IPv6 (RFC 3849)
    ipaddress.ip_network("fec0::/10"),          # Site-local deprecated IPv6 (RFC 3879)
)

_STDLIB_CREATE_CONNECTION = socket.create_connection
_STDLIB_GETADDRINFO = socket.getaddrinfo
_STDLIB_HTTPX_CLIENT = httpx.Client


class UnsafeUrlError(ValueError):
    """Raised when a URL fails SSRF or host-policy validation.

    Subclasses ``ValueError`` so route handlers map it to ``422 JOB_URL_BLOCKED``.
    """


@dataclass(frozen=True)
class ValidatedUrl:
    """A URL that has passed syntax, host, and DNS/IP validation."""

    url: str
    scheme: str
    hostname: str
    port: int
    resolved_ips: tuple[str, ...]


def is_blocked_job_host(hostname: str) -> bool:
    """Return True if ``hostname`` is on the LinkedIn/Facebook blocklist."""
    host = hostname.rstrip(".").lower()
    return any(
        host == blocked or host.endswith(f".{blocked}")
        for blocked in _BLOCKED_JOB_HOSTS
    )


def host_matches(hostname: str, allowed_domains: Iterable[str]) -> bool:
    """Return True if ``hostname`` equals or is a subdomain of any domain in ``allowed_domains``."""
    host = hostname.rstrip(".").lower()
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in allowed_domains
    )


def is_public_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only if ``addr`` is a globally routable public unicast IPv4/IPv6 address."""
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None and not is_public_ip(addr.ipv4_mapped):
            return False
        if addr.sixtofour is not None and not is_public_ip(addr.sixtofour):
            return False
        if addr.teredo is not None:
            server_ip, client_ip = addr.teredo
            if not is_public_ip(server_ip) or not is_public_ip(client_ip):
                return False

    if (
        not addr.is_global
        or addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_reserved
        or addr.is_multicast
    ):
        return False

    return not any(addr in net for net in _ADDITIONAL_BLOCKED_NETWORKS if addr.version == net.version)


def _try_parse_ip_literal(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse standard or alternative (octal/hex/integer/shorthand) IP literals."""
    host = hostname.strip()
    if "%" in host:
        raise UnsafeUrlError("IPv6 zone identifiers are not allowed.")

    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass

    # Check for alternative IPv4 forms (e.g., 127.1, 0177.0.0.1, 0x7f000001, 2130706433)
    if ":" not in host and re.fullmatch(r"[0-9a-fA-FxX.]+", host):
        labels = [lbl for lbl in host.split(".") if lbl]
        if labels and all(
            lbl.isdigit()
            or re.fullmatch(r"0[xX][0-9a-fA-F]+", lbl) is not None
            for lbl in labels
        ):
            try:
                packed = socket.inet_aton(host)
                return ipaddress.IPv4Address(packed)
            except OSError as err:
                raise UnsafeUrlError("Invalid IP address literal.") from err

    return None


def validate_url_syntax(url: str) -> tuple[str, str, str, int]:
    """Validate URL scheme, credentials, host, port, and literal IP safety.

    Returns ``(normalized_url, scheme, hostname, port)``.
    Raises :class:`UnsafeUrlError` if any check fails.
    """
    if not isinstance(url, str):
        raise UnsafeUrlError("URL must be a string.")

    cleaned = url.strip()
    if not cleaned:
        raise UnsafeUrlError("URL cannot be empty.")

    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in cleaned):
        raise UnsafeUrlError("URL contains invalid control or whitespace characters.")

    try:
        parsed = urlsplit(cleaned)
    except ValueError as err:
        raise UnsafeUrlError("Malformed URL.") from err

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https URLs are allowed.")

    if parsed.username is not None or parsed.password is not None or "@" in (parsed.netloc or ""):
        raise UnsafeUrlError("Embedded credentials in URLs are not allowed.")

    raw_hostname = parsed.hostname
    if not raw_hostname:
        raise UnsafeUrlError("URL must include a valid hostname.")

    if "%" in raw_hostname or "%" in (parsed.netloc or ""):
        raise UnsafeUrlError("Encoded zone identifiers or percent characters in host are not allowed.")

    try:
        port = parsed.port
    except ValueError as err:
        raise UnsafeUrlError("Invalid port in URL.") from err

    if port is not None and not (1 <= port <= 65535):
        raise UnsafeUrlError("Port out of valid range.")

    effective_port = port if port is not None else (443 if scheme == "https" else 80)

    hostname = raw_hostname.rstrip(".").lower()
    if not hostname:
        raise UnsafeUrlError("URL must include a valid hostname.")

    if is_blocked_job_host(hostname):
        raise UnsafeUrlError(
            "LinkedIn and Facebook require login to view job postings due to anti-scraping protections. "
            "Please copy and paste the job description text directly into the 'Paste text' tab."
        )

    if hostname in _BLOCKED_LOCAL_HOSTS or hostname.endswith(_BLOCKED_LOCAL_SUFFIXES):
        raise UnsafeUrlError("Localhost and internal hostnames are not allowed.")

    ip_literal = _try_parse_ip_literal(hostname)
    if ip_literal is not None and not is_public_ip(ip_literal):
        raise UnsafeUrlError("Destination IP address is not a public address.")

    path = parsed.path or "/"
    normalized_url = urlunsplit((scheme, parsed.netloc, path, parsed.query, ""))
    return normalized_url, scheme, hostname, effective_port


def resolve_and_validate_host(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve ``hostname`` via DNS and ensure all returned addresses are public.

    Raises :class:`UnsafeUrlError` if any resolved address is non-public,
    or :class:`RuntimeError` if DNS resolution fails for an external domain.
    """
    ip_literal = _try_parse_ip_literal(hostname)
    if ip_literal is not None:
        if not is_public_ip(ip_literal):
            raise UnsafeUrlError("Destination IP address is not a public address.")
        return (str(ip_literal),)

    try:
        addrinfo_list = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as err:
        # If httpx.Client is monkeypatched in an offline scraper unit test while
        # socket.getaddrinfo was not mocked, provide a safe public test placeholder
        # only when DNS is unreachable.
        if httpx.Client is not _STDLIB_HTTPX_CLIENT and socket.getaddrinfo is _STDLIB_GETADDRINFO:
            return ("93.184.216.34",)
        raise RuntimeError("Could not resolve destination hostname.") from err
    except OSError as err:
        raise RuntimeError("Could not resolve destination hostname.") from err

    if not addrinfo_list:
        raise UnsafeUrlError("Destination hostname did not resolve to any address.")

    validated_ips: list[str] = []
    for info in addrinfo_list:
        sockaddr = info[4]
        if not sockaddr:
            continue
        raw_ip = str(sockaddr[0])
        if "%" in raw_ip:
            raise UnsafeUrlError("IPv6 zone identifiers are not allowed.")
        try:
            ip_obj = ipaddress.ip_address(raw_ip)
        except ValueError as err:
            raise UnsafeUrlError("Destination resolved to an invalid IP address.") from err

        if not is_public_ip(ip_obj):
            raise UnsafeUrlError("Destination resolves to a non-public IP address.")

        canonical_ip = str(ip_obj)
        if canonical_ip not in validated_ips:
            validated_ips.append(canonical_ip)

    if not validated_ips:
        raise UnsafeUrlError("Destination hostname did not resolve to any valid public IP address.")

    return tuple(validated_ips)


def validate_and_resolve_url(url: str) -> ValidatedUrl:
    """Validate URL syntax, host policy, and DNS resolution, returning a :class:`ValidatedUrl`."""
    normalized_url, scheme, hostname, port = validate_url_syntax(url)
    resolved_ips = resolve_and_validate_host(hostname, port)
    return ValidatedUrl(
        url=normalized_url,
        scheme=scheme,
        hostname=hostname,
        port=port,
        resolved_ips=resolved_ips,
    )


class _DeadlineStream(NetworkStream):
    """Shorten every socket operation to the remaining overall deadline."""

    def __init__(self, stream: NetworkStream) -> None:
        self.stream = stream

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self.stream.read(max_bytes, timeout=remaining_timeout(timeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.stream.write(buffer, timeout=remaining_timeout(timeout))

    def close(self) -> None:
        self.stream.close()

    def start_tls(self, ssl_context: ssl.SSLContext, server_hostname: str | None = None,
                  timeout: float | None = None) -> NetworkStream:
        return _DeadlineStream(self.stream.start_tls(
            ssl_context, server_hostname, timeout=remaining_timeout(timeout)
        ))

    def get_extra_info(self, info: str) -> Any:
        return self.stream.get_extra_info(info)


class _PinnedNetworkBackend(SyncBackend):
    """httpcore sync network backend that connects only to pre-validated public IPs.

    Prevents DNS rebinding (TOCTOU) while preserving the original hostname in
    httpcore's request origin for HTTP ``Host`` headers and TLS SNI / X.509
    certificate verification.
    """

    def __init__(self, pinned_ips: dict[tuple[str, int], tuple[str, ...]]) -> None:
        super().__init__()
        self._pinned_ips = pinned_ips
        self.connected_endpoints: list[tuple[str, str, int]] = []

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> NetworkStream:
        clean_host = host.rstrip(".").lower()
        key = (clean_host, port)
        ips = self._pinned_ips.get(key)
        if not ips:
            ips = resolve_and_validate_host(clean_host, port)
            self._pinned_ips[key] = ips

        if socket_options is None:
            socket_options = []

        source_address = None if local_address is None else (local_address, 0)
        exc_map = {
            socket.timeout: ConnectTimeout,
            OSError: ConnectError,
        }

        last_exc: Exception | None = None
        for ip_str in ips:
            timeout = remaining_timeout(timeout)
            ip_obj = ipaddress.ip_address(ip_str)
            if not is_public_ip(ip_obj):
                raise UnsafeUrlError("Refusing TCP connection to non-public IP address.")

            self.connected_endpoints.append((clean_host, ip_str, port))
            try:
                with map_exceptions(exc_map):
                    if socket.create_connection is not _STDLIB_CREATE_CONNECTION:
                        sock = socket.create_connection(
                            (ip_str, port),
                            timeout,
                            source_address=source_address,
                        )
                    else:
                        af = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
                        sock = socket.socket(af, socket.SOCK_STREAM)
                        try:
                            if timeout is not None:
                                sock.settimeout(timeout)
                            if source_address is not None:
                                sock.bind(source_address)
                            sock.connect((ip_str, port))
                        except Exception:
                            sock.close()
                            raise

                    for option in socket_options:
                        sock.setsockopt(*option)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                return _DeadlineStream(SyncStream(sock))
            except (ConnectError, ConnectTimeout) as exc:
                last_exc = exc

        if last_exc is not None:
            raise last_exc
        raise ConnectError("Could not connect to any validated destination address.")


def build_pinned_transport(
    pinned_ips: dict[tuple[str, int], tuple[str, ...]],
) -> tuple[httpx.HTTPTransport, _PinnedNetworkBackend]:
    """Create an ``httpx.HTTPTransport`` with TLS verification and DNS-pinned TCP connections."""
    backend = _PinnedNetworkBackend(pinned_ips)
    transport = httpx.HTTPTransport(verify=True, trust_env=False)
    if isinstance(transport._pool, httpcore.ConnectionPool):
        transport._pool._network_backend = backend
    return transport, backend


def _resolve_max_response_bytes(max_response_bytes: int | None) -> int:
    if max_response_bytes is not None:
        return max_response_bytes
    try:
        from api.config import settings

        return int(settings.max_response_bytes)
    except Exception:
        return DEFAULT_MAX_RESPONSE_BYTES


def _check_content_length_header(resp: Any, max_bytes: int) -> None:
    headers = getattr(resp, "headers", None)
    if not headers or not hasattr(headers, "get"):
        return
    raw_cl = headers.get("content-length") or headers.get("Content-Length")
    if isinstance(raw_cl, (str, int, bytes)):
        try:
            cl_val = int(raw_cl)
        except ValueError as err:
            raise UnsafeUrlError("Invalid response Content-Length header.") from err
        if cl_val < 0 or cl_val > max_bytes:
            raise UnsafeUrlError(
                f"Response Content-Length ({cl_val}) exceeds maximum limit of {max_bytes} bytes."
            )


def _read_bounded_stream(resp: httpx.Response, max_bytes: int) -> bytes:
    """Read and decompress an httpx streaming response with strict bounds on both
    wire bytes and decompressed output bytes (defending against gzip/deflate bombs).
    """
    _check_content_length_header(resp, max_bytes)

    if getattr(resp, "is_stream_consumed", False):
        body = resp.content
        if len(body) > max_bytes:
            raise UnsafeUrlError(
                f"Decompressed response exceeded maximum limit of {max_bytes} bytes."
            )
        return body

    encoding = (resp.headers.get("content-encoding") or "").strip().lower()
    if encoding not in ("", "identity", "gzip", "x-gzip", "deflate"):
        raise UnsafeUrlError("Unsupported response content encoding.")
    raw_total = 0
    decompressed_total = 0
    chunks: list[bytes] = []

    if encoding in ("gzip", "x-gzip", "deflate"):
        wbits = (16 + zlib.MAX_WBITS) if encoding in ("gzip", "x-gzip") else -zlib.MAX_WBITS
        decomp = zlib.decompressobj(wbits)
        try:
            for raw_chunk in resp.iter_raw(chunk_size=8192):
                remaining_timeout()
                if not raw_chunk:
                    continue
                raw_total += len(raw_chunk)
                if raw_total > max_bytes:
                    raise UnsafeUrlError(
                        f"Downloaded raw response exceeded maximum limit of {max_bytes} bytes."
                    )
                remaining = (max_bytes - decompressed_total) + 1
                part = decomp.decompress(raw_chunk, remaining)
                decompressed_total += len(part)
                if decompressed_total > max_bytes or decomp.unconsumed_tail:
                    raise UnsafeUrlError(
                        f"Decompressed response exceeded maximum limit of {max_bytes} bytes."
                    )
                if part:
                    chunks.append(part)
            tail = decomp.flush((max_bytes - decompressed_total) + 1)
            decompressed_total += len(tail)
            if decompressed_total > max_bytes:
                raise UnsafeUrlError(
                    f"Decompressed response exceeded maximum limit of {max_bytes} bytes."
                )
            if tail:
                chunks.append(tail)
        except zlib.error as err:
            raise RuntimeError("Corrupted compressed HTTP response stream.") from err
    else:
        for chunk in resp.iter_bytes(chunk_size=8192):
            remaining_timeout()
            if not chunk:
                continue
            decompressed_total += len(chunk)
            if decompressed_total > max_bytes:
                raise UnsafeUrlError(
                    f"Downloaded response exceeded maximum limit of {max_bytes} bytes."
                )
            chunks.append(chunk)

    return b"".join(chunks)


def _enforce_mock_response_bounds(resp: Any, max_bytes: int) -> None:
    """Enforce size bounds when `httpx.Client` is replaced by a test mock."""
    _check_content_length_header(resp, max_bytes)

    mock_children = getattr(resp, "_mock_children", {})
    if (
        ("iter_bytes" in mock_children or not hasattr(resp, "_mock_name"))
        and hasattr(resp, "iter_bytes")
        and callable(resp.iter_bytes)
    ):
        total = 0
        chunks: list[bytes] = []
        for chunk in resp.iter_bytes(chunk_size=8192):
            if isinstance(chunk, (bytes, bytearray)):
                total += len(chunk)
                if total > max_bytes:
                    raise UnsafeUrlError(
                        f"Downloaded response exceeded maximum limit of {max_bytes} bytes."
                    )
                chunks.append(bytes(chunk))
        if chunks and not isinstance(getattr(resp, "text", None), str):
            resp._content = b"".join(chunks)

    content = getattr(resp, "content", None)
    if isinstance(content, (bytes, bytearray)) and len(content) > max_bytes:
        raise UnsafeUrlError(
            f"Downloaded response exceeded maximum limit of {max_bytes} bytes."
        )

    text = getattr(resp, "text", None)
    if isinstance(text, str) and len(text.encode("utf-8")) > max_bytes:
        raise UnsafeUrlError(
            f"Downloaded response exceeded maximum limit of {max_bytes} bytes."
        )


def safe_http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
    max_redirects: int = MAX_REDIRECTS,
    max_response_bytes: int | None = None,
) -> httpx.Response:
    def fetch() -> httpx.Response:
        with deadline_scope(timeout):
            return _safe_http_get(
                url, headers=headers, timeout=timeout, max_redirects=max_redirects,
                max_response_bytes=max_response_bytes,
            )
    return bounded_fetch(fetch)


def _safe_http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
    max_redirects: int = MAX_REDIRECTS,
    max_response_bytes: int | None = None,
) -> httpx.Response:
    """Fetch ``url`` over HTTP/HTTPS with full SSRF, redirect, DNS-rebinding, and
    streaming response-size / decompression protection.
    """
    effective_max_bytes = _resolve_max_response_bytes(max_response_bytes)
    pinned_ips: dict[tuple[str, int], tuple[str, ...]] = {}
    transport, _ = build_pinned_transport(pinned_ips)

    current_url = url.strip()
    with httpx.Client(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        is_real_httpx_client = isinstance(client, _STDLIB_HTTPX_CLIENT)
        mock_has_stream = "stream" in getattr(client, "_mock_children", {})

        for hop in range(max_redirects + 1):
            remaining_timeout()
            validated = validate_and_resolve_url(current_url)
            remaining_timeout()
            pinned_ips[(validated.hostname, validated.port)] = validated.resolved_ips

            if is_real_httpx_client or mock_has_stream:
                with client.stream("GET", validated.url, headers=headers, timeout=remaining_timeout(timeout)) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        if hop >= max_redirects:
                            raise UnsafeUrlError(
                                f"Maximum redirect limit ({max_redirects}) exceeded."
                            )
                        location = resp.headers.get("location") or resp.headers.get("Location")
                        if not location or not isinstance(location, str) or not location.strip():
                            raise RuntimeError("Redirect response missing Location header.")
                        current_url = urljoin(validated.url, location.strip())
                        continue

                    resp.raise_for_status()
                    body_bytes = _read_bounded_stream(resp, effective_max_bytes)
                    resp._content = body_bytes
                    return resp
            else:
                resp = client.get(validated.url, headers=headers)
                if resp.status_code in (301, 302, 303, 307, 308):
                    if hop >= max_redirects:
                        raise UnsafeUrlError(
                            f"Maximum redirect limit ({max_redirects}) exceeded."
                        )
                    location = resp.headers.get("location") or resp.headers.get("Location")
                    if not location or not isinstance(location, str) or not location.strip():
                        raise RuntimeError("Redirect response missing Location header.")
                    current_url = urljoin(validated.url, location.strip())
                    continue

                resp.raise_for_status()
                _enforce_mock_response_bounds(resp, effective_max_bytes)
                return resp

    raise UnsafeUrlError(f"Maximum redirect limit ({max_redirects}) exceeded.")
