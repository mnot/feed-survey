from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Normalize URL to help matching between autodiscovery and processing."""
    if not url:
        return ""
    if "?" not in url and "#" not in url:
        return url.strip().lower().rstrip("/")

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path:
        path = "/"
    return urlunparse(
        (parsed.scheme, parsed.netloc.lower(), path, "", parsed.query, "")
    )


def get_domain(url: str) -> str:
    """High-performance extraction of domain from URL."""
    if url.startswith("http"):
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
            return netloc[:port_idx]
        return netloc
    return url.split("/", 1)[0]
