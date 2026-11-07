"""Requests the server makes on someone's behalf: web sources and S3 endpoints. Unless private URLs are
allowed (`ROWLAB_PRIVATE_URLS`, on locally), they can only reach public addresses, so nobody can make
the server fetch from its own network or the cloud's metadata service (SSRF).

The address is checked when the request is made, and again on every redirect. Two ways past it are
left to the network a hosted rowlab runs in, which must block private addresses too: a DNS server that
answers differently the second time, and S3 endpoints, which DuckDB reaches itself and follows
redirects from without asking.
"""

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from rowlab import __version__
from rowlab.core.config import config
from rowlab.core.errors import InvalidRequest


def check_url(url: str) -> None:
    """Raise InvalidRequest unless the URL is http(s) to a public address (or private ones are
    allowed)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise InvalidRequest(f"{url} isn't an http(s) URL.")
    if config().private_urls:
        return
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        found = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except (OSError, ValueError) as e:
        raise InvalidRequest(f"Could not reach {url}: {describe(e, parsed.hostname)}.") from e
    for *_, address in found:
        ip = ipaddress.ip_address(address[0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise InvalidRequest(
                f"{parsed.hostname} is a private address, which rowlab can't reach here."
            )


def describe(error: object, hostname: str | None) -> str:
    """Why a request failed, in words: no errno, nor the platform's name-lookup jargon."""
    if isinstance(error, socket.gaierror):
        return f"{hostname} wasn't found"
    return getattr(error, "strerror", None) or str(error)


def open_url(url: str, timeout: float) -> Any:
    """GET a URL, checking it and every redirect."""
    check_url(url)
    # Some hosts reject Python's default user agent.
    request = Request(url, headers={"User-Agent": f"rowlab/{__version__}"})
    return build_opener(_CheckedRedirects()).open(request, timeout=timeout)


class _CheckedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)
