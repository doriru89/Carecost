"""Who is asking, as keyed hashes only (D2, P8). The raw IP and email are never stored or logged.

- The client IP comes from ONE configured trusted proxy header, or the socket peer when none is
  configured. Any other header (X-Real-IP, a second X-Forwarded-For entry the client wrote itself)
  is ignored: a client can put anything in a header, only the proxy's own append is trusted.
- IPv6 is keyed by its /64 (one home or phone network gets a whole /64, so per-address keys would
  let one person rotate through 2^64 identities). IPv4-mapped IPv6 is treated as IPv4.
- Both are HMAC-SHA256 with a secret from env, so the ledger cannot be reversed by brute-forcing
  the IPv4 space or a list of emails.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from typing import Any


class ClientAddressError(ValueError):
    """The trusted proxy header is configured but missing or malformed."""


def client_ip(
    headers: Any,
    peer: str | None,
    trusted_header: str | None,
    hops: int = 1,
) -> str:
    """The client address as a string. ``headers`` is a case-insensitive mapping (Starlette)."""
    if not trusted_header:
        if not peer:
            raise ClientAddressError("no client address")
        return _parse(peer)
    raw = headers.get(trusted_header)
    if not raw:
        raise ClientAddressError(f"trusted proxy header {trusted_header} is missing")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if trusted_header.lower() == "x-forwarded-for":
        # each trusted proxy appends the address it saw; the client controls everything left of it
        if len(parts) < hops:
            raise ClientAddressError("X-Forwarded-For has fewer entries than trusted hops")
        return _parse(parts[-hops])
    if len(parts) != 1:
        raise ClientAddressError(f"{trusted_header} must hold exactly one address")
    return _parse(parts[0])


def _parse(s: str) -> str:
    s = s.strip()
    if s.startswith("[") and "]" in s:  # [v6]:port
        s = s[1 : s.index("]")]
    elif s.count(":") == 1:  # v4:port
        s = s.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(s))
    except ValueError as e:
        raise ClientAddressError(f"not an IP address: {s!r}") from e


def ip_key(ip: str) -> str:
    """IPv4 as is; IPv6 as its /64 network; IPv4-mapped IPv6 as the IPv4."""
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.IPv6Network(f"{addr}/64", strict=False))
    return str(addr)


def keyed_hash(secret: bytes, kind: str, value: str) -> str:
    return hmac.new(secret, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def hash_ip(secret: bytes, ip: str) -> str:
    return keyed_hash(secret, "ip", ip_key(ip))


def hash_email(secret: bytes, email: str) -> str:
    return keyed_hash(secret, "email", email.strip().lower())
