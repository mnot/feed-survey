from ipaddress import ip_address
from urllib.parse import ParseResult, urlparse, urlunparse

from publicsuffix2 import get_sld


def normalize_url(url: str) -> str:
    """Normalize URL to help matching between autodiscovery and processing."""
    return _normalize_url(url, keep_query=True)


def normalize_url_for_grouping(url: str) -> str:
    """Normalize URL for grouping where query strings should not define identity."""
    return _normalize_url(url, keep_query=False)


def _normalize_url(url: str, keep_query: bool) -> str:
    if not url:
        return ""

    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    if not path:
        path = "/"
    query = parsed.query if keep_query else ""
    return urlunparse(
        (parsed.scheme.lower(), _normalize_netloc(parsed), path, "", query, "")
    )


def _normalize_netloc(parsed: ParseResult) -> str:
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return parsed.netloc.lower()

    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0].lower() + "@"

    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"

    try:
        port = parsed.port
    except ValueError:
        return parsed.netloc.lower()

    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    if port is None or default_port:
        return f"{userinfo}{hostname}"
    return f"{userinfo}{hostname}:{port}"


def get_host(url: str) -> str:
    """Extract the normalized URL host."""
    if url.lower().startswith("http"):
        return (urlparse(url).hostname or "").lower()
    return url.split("/", 1)[0].lower()


def get_site(url: str) -> str:
    """Extract the registrable site for a URL or host.

    This uses the Public Suffix List for DNS names. IP literals and localhost-like
    names fall back to the host itself because they do not have a registrable
    domain.
    """
    host = get_host(url).strip(".")
    if not host:
        return ""
    try:
        ip_address(host)
        return host
    except ValueError:
        pass
    return (get_sld(host) or host).lower()


def get_domain(url: str) -> str:
    """Extract the normalized URL host.

    Prefer get_site() when grouping web properties for the report. This function
    is retained for host-level callers and tests.
    """
    return get_host(url)
