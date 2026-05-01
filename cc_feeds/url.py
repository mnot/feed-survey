from urllib.parse import urlparse, urlunparse


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
        (parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, "")
    )


def get_domain(url: str) -> str:
    """High-performance extraction of domain from URL."""
    if url.lower().startswith("http"):
        start = url.find("//") + 2
        end = url.find("/", start)
        if end == -1:
            end = url.find("?", start)
        if end == -1:
            end = url.find("#", start)
        if end == -1:
            end = len(url)

        netloc = url[start:end]
        port_idx = netloc.find(":")
        if port_idx != -1:
            return netloc[:port_idx].lower()
        return netloc.lower()
    return url.split("/", 1)[0].lower()
