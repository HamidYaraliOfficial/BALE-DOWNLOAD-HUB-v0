"""URL validation and SSRF protection.

Every hop of a redirect chain must be passed through `validate_url` again.
Known residual risk (documented in docs/SECURITY.md): DNS rebinding between the
validation lookup and the connection made by the HTTP library (TOCTOU).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from app.core.exceptions import UrlBlockedError

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
                     "metadata.google.internal", "instance-data"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet", ".corp")
MAX_URL_LENGTH = 2048
_CONTROL = re.compile(r"[\x00-\x20\x7f]")

Resolver = Callable[[str, int], list[str]]


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out: list[str] = []
    for fam, _t, _p, _c, sa in infos:
        ip = sa[0]
        if ip not in out:
            out.append(ip)
    return out


def is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
        elif ip.teredo is not None:
            return False
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified):
        return False
    return bool(ip.is_global)


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    scheme: str
    host: str
    port: int
    ips: tuple[str, ...] = field(default_factory=tuple)


def validate_url(url: str, resolver: Resolver | None = None, allow_private: bool = False) -> ValidatedUrl:
    """Raise UrlBlockedError unless `url` is an http(s) URL whose every resolved IP is public."""
    if not isinstance(url, str) or not url.strip():
        raise UrlBlockedError("empty url", code="url_empty")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise UrlBlockedError("url too long", code="url_too_long")
    if _CONTROL.search(url):
        raise UrlBlockedError("url contains whitespace/control characters", code="url_invalid")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise UrlBlockedError(f"malformed url: {e}", code="url_invalid") from e
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UrlBlockedError("only http/https are allowed", code="url_scheme")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UrlBlockedError("missing host", code="url_invalid")
    if parts.username is not None or parts.password is not None:
        raise UrlBlockedError("credentials in URL are not allowed", code="url_credentials")
    if port is None:
        port = 443 if scheme == "https" else 80
    if port == 0:
        raise UrlBlockedError("invalid port", code="url_invalid")
    if allow_private:
        return ValidatedUrl(url, scheme, host, port, ())
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise UrlBlockedError("host is not public", code="url_private")
    # IP literal, including legacy decimal/hex/octal IPv4 forms ("2130706433", "0x7f.1")
    ips: list[str] | None = None
    try:
        ips = [str(ipaddress.ip_address(host))]
    except ValueError:
        if re.fullmatch(r"[0-9a-fx.]+", host):
            try:
                ips = [socket.inet_ntoa(socket.inet_aton(host))]
            except OSError:
                ips = None
    if ips is None:
        try:
            ips = (resolver or system_resolver)(host, port)
        except (socket.gaierror, OSError) as e:
            raise UrlBlockedError(f"DNS resolution failed: {e}", code="url_dns") from e
    if not ips:
        raise UrlBlockedError("no address", code="url_dns")
    for ip in ips:
        if not is_public_ip(ip):
            raise UrlBlockedError("destination resolves to a private/reserved address", code="url_private")
    return ValidatedUrl(url, scheme, host, port, tuple(ips))


def normalize_url(url: str) -> str:
    """Canonical form used for duplicate detection."""
    p = urlsplit(url.strip())
    scheme = p.scheme.lower()
    host = (p.hostname or "").lower()
    port = p.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = p.path or "/"
    return urlunsplit((scheme, host, path, p.query, ""))
