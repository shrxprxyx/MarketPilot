"""Outbound-request guard shared by the AI gateway (provider base URLs) and the audit crawler
(client sites). Only http(s) is allowed, and the host must not resolve to a link-local or
otherwise non-routable address (this covers cloud metadata endpoints). Loopback and
private-network addresses are refused unless the caller allows them (a deployment choice).

The name is resolved again when the request connects, so this guards against misconfiguration
and casual abuse; it is not a defence against DNS rebinding."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeDestination(Exception):
    """`kind` is one of: scheme, resolve, blocked, private."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


async def check_destination(url: str, *, allow_private: bool) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeDestination("scheme")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        infos = await asyncio.get_running_loop().getaddrinfo(
            parts.hostname, port, type=socket.SOCK_STREAM
        )
    except (OSError, ValueError) as exc:
        raise UnsafeDestination("resolve") from exc
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise UnsafeDestination("blocked")
        # Order matters: ::1 is both loopback and "reserved", 240.0.0.0/4 both private and
        # reserved. Loopback is a deployment choice; reserved ranges are never valid.
        if not ip.is_loopback and ip.is_reserved:
            raise UnsafeDestination("blocked")
        if (ip.is_loopback or ip.is_private) and not allow_private:
            raise UnsafeDestination("private")
