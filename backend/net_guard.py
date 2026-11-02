"""
Outbound-URL safety for merchant-configured endpoints (Discord / WhatsApp webhooks, SMTP host).

Two layers:
- `is_public_https_url(url)` (save time, no DNS): https only, no localhost / *.local / *.internal,
  and any IPv4 spelling (127.1, 0x7f.0.0.1, 2130706433, ...) is normalised with inet_aton and
  must be a global address.
- `host_resolves_public(host)` (send time): every address the name resolves to must be global,
  so a public-looking name pointing at 127.0.0.1 / 10.x / 169.254.x is refused. A DNS failure is
  not treated as a block: the request itself would fail on the same resolver.
"""
import ipaddress
import re
import socket
from typing import Optional
from urllib.parse import urlparse

_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".localdomain", ".home.arpa")
_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$")


def _literal_ip(host: str) -> Optional[ipaddress._BaseAddress]:
    """The IP a host string denotes literally (incl. legacy IPv4 forms), or None for a name."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.inet_aton(host))  # 127.1, 0x7f.0.0.1, 2130706433 ...
    except (OSError, ValueError):
        return None


def is_public_host(host: Optional[str]) -> bool:
    """Syntax-level check (no DNS): a global IP literal or a normal DNS name that is not local."""
    h = (host or "").strip().lower().rstrip(".")
    if not h or h == "localhost" or h.endswith(_BLOCKED_SUFFIXES):
        return False
    ip = _literal_ip(h)
    if ip is not None:
        return bool(ip.is_global)
    return bool(_HOST_RE.match(h))


def is_public_https_url(value: Optional[str]) -> bool:
    """True for an https URL whose host passes is_public_host (no DNS lookup)."""
    try:
        parsed = urlparse((value or "").strip())
    except Exception:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    return is_public_host(parsed.hostname)


def host_resolves_public(host: Optional[str], port: int = 443) -> bool:
    """
    Send-time check: False if the host is not public by syntax, or if ANY resolved address is
    not global. DNS errors return True (the connection attempt fails on its own).
    """
    if not is_public_host(host):
        return False
    h = (host or "").strip().lower().rstrip(".")
    if _literal_ip(h) is not None:
        return True
    try:
        infos = socket.getaddrinfo(h, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return True
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False
        except ValueError:
            return False
    return True


def url_resolves_public(value: Optional[str]) -> bool:
    """is_public_https_url + host_resolves_public for the URL's host."""
    if not is_public_https_url(value):
        return False
    parsed = urlparse((value or "").strip())
    return host_resolves_public(parsed.hostname, parsed.port or 443)
