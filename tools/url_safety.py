"""URL safety validation for browser_tool and other network-facing tools.

Implements SSRF (Server-Side Request Forgery) protection by:
- Rejecting private/reserved IP ranges (RFC 1918, loopback, link-local)
- Blocking cloud metadata endpoints (AWS/GCP/Azure/Oracle/etc.)
- Enforcing URL scheme allowlist
- Rejecting DNS rebinding by resolving hostnames before validation
"""

import ipaddress
import logging
import re
import socket
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Allowed URL schemes (others are stripped or rejected)
_ALLOWED_SCHEMES = {"http", "https"}

# Syntactically valid private/reserved IP ranges
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),      # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),   # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918
    ipaddress.ip_network("127.0.0.0/8"),     # Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("100.64.0.0/10"),   # Shared address space (CGNAT)
    ipaddress.ip_network("192.0.0.0/24"),   # IANA special
    ipaddress.ip_network("192.0.2.0/24"),    # TEST-NET-1
    ipaddress.ip_network("192.88.99.0/24"),  # 6to4 Relay anycast
    ipaddress.ip_network("198.18.0.0/15"),   # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"), # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),     # Multicast
    ipaddress.ip_network("240.0.0.0/4"),     # Reserved / multicast
    ipaddress.ip_network("::1/128"),         # Loopback IPv6
    ipaddress.ip_network("fe80::/10"),       # Link-local IPv6
    ipaddress.ip_network("fc00::/7"),        # Unique local IPv6
    ipaddress.ip_network("::ffff:0:0/96"),   # IPv4-mapped IPv6
]

# Known cloud metadata endpoints that must never be accessible from the agent
_CLOUD_METADATA_ENDPOINTS = [
    # AWS
    "169.254.169.254",  # EC2 IMDS
    # GCP
    "metadata.google.internal", "169.254.169.254",
    # Azure
    "169.254.169.254",  # Azure IMDS
    # Oracle Cloud
    "169.254.169.254",
    # Alibaba Cloud
    "100.100.100.200",
    # DigitalOcean
    "169.254.169.254",
    # Hetzner
    "169.254.169.254",
]

# Hostname patterns that are always blocked regardless of DNS resolution
_BLOCKED_HOST_PATTERNS = [
    re.compile(r"^169\.254\.169\.254$"),
    re.compile(r"^localhost$", re.I),
    re.compile(r"^127\.[0-9]+\.[0-9]+\.[0-9]+$"),
    re.compile(r"^::1$"),
    re.compile(r"^0\.0\.0\.0$"),
    re.compile(r"\.internal$", re.I),
    re.compile(r"^metadata\.", re.I),
    re.compile(r"^instance-data\.", re.I),
]


def _is_private_ip(addr: str) -> bool:
    """Return True if addr is a private/reserved IP."""
    try:
        ip = ipaddress.ip_address(addr)
        return any(ip in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


def _is_blocked_host(hostname: str) -> bool:
    """Return True if hostname matches a blocked pattern."""
    host = hostname.lower().strip()
    if not host:
        return True
    for pattern in _BLOCKED_HOST_PATTERNS:
        if pattern.search(host):
            return True
    return False


def _resolve_hostname(host: str) -> Optional[str]:
    """Resolve hostname to first IP address, or None if unresolvable."""
    if _is_blocked_host(host):
        return None
    if _is_private_ip(host):
        return host  # Already an IP, already checked
    try:
        resolved = socket.getaddrinfo(host, None, socket.AF_UNSPEC)
        for family, _, _, _, sockaddr in resolved:
            ip = sockaddr[0]
            if _is_private_ip(ip):
                return None
            if _is_blocked_host(ip):
                return None
            return ip  # Return first public IP
    except Exception:
        return None


def is_safe_url(url: str, *, resolve_dns: bool = True) -> tuple[bool, str]:
    """Validate a URL against SSRF and private-IP protections.

    Returns:
        (is_safe: bool, reason: str)
        On success: (True, "")
        On failure: (False, "human-readable rejection reason")
    """
    if not isinstance(url, str) or not url.strip():
        return False, "URL is empty"

    # Strip whitespace and trailing junk (bidi attacks, etc.)
    raw = url.strip().strip("\u200e\u200f\u202a-\u202e\u2066-\u2069")

    # Parse URL
    try:
        parsed = urlparse(raw)
    except Exception:
        return False, "Malformed URL"

    scheme = (parsed.scheme or "").lower()
    if not scheme:
        # No scheme — attempt default https and re-check
        return is_safe_url(f"https://{raw}", resolve_dns=resolve_dns)

    if scheme not in _ALLOWED_SCHEMES:
        return False, f"Disallowed URL scheme: {scheme}"

    host = (parsed.hostname or "").lower().strip()
    if not host:
        return False, "URL missing host"

    # Block known metadata hostnames immediately
    if _is_blocked_host(host):
        return False, f"Blocked hostname: {host}"

    # Check IP literal
    if _is_private_ip(host):
        return False, f"Private IP address not allowed: {host}"

    # DNS resolution check (rebinding protection)
    if resolve_dns:
        resolved = _resolve_hostname(host)
        if resolved is None:
            return False, f"Host resolves to private IP or is blocked: {host}"

    return True, ""


def maybe_block_url(url: str) -> Optional[dict]:
    """
    Return a block dict (compatible with browser_tool output format) if URL
    is unsafe, or None if it's safe.  Used by browser_navigate and friends.
    """
    safe, reason = is_safe_url(url)
    if safe:
        return None
    return {
        "success": False,
        "error": reason,
        "blocked_by_policy": {"rule": "url_safety", "url": url, "reason": reason},
    }
