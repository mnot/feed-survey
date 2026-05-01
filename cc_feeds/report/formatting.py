from typing import Any, Dict, Union

_NS_PREFIXES: Dict[str, str] = {
    "http://purl.org/dc/elements/1.1/": "dc",
    "http://purl.org/dc/terms/": "dcterms",
    "http://search.yahoo.com/mrss/": "media",
    "http://purl.org/rss/1.0/modules/content/": "content",
    "http://purl.org/rss/1.0/modules/slash/": "slash",
    "http://purl.org/rss/1.0/modules/syndication/": "sy",
    "http://www.w3.org/2003/01/geo/wgs84_pos#": "geo",
    "http://www.georss.org/georss/": "georss",
    "http://schemas.google.com/g/2005#": "gd",
    "http://wellformedweb.org/CommentAPI/": "wfw",
    "http://webfeeds.org/rss/1.0": "webfeeds",
    "http://purl.org/rss/1.0/modules/company/": "co",
    "http://purl.org/rss/1.0/modules/event/": "ev",
}


def format_extension(ext: Any) -> str:
    """Format a (namespace_uri, localname) tuple as a readable prefix:local string."""
    if isinstance(ext, (tuple, list)) and len(ext) == 2:
        ns, local = str(ext[0]), str(ext[1])
        prefix = _NS_PREFIXES.get(ns)
        if prefix:
            return f"{prefix}:{local}"

        stripped = ns.rstrip("/#")
        part = stripped.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if part:
            return f"{part}:{local}"
        return local
    return str(ext)


def format_number(value: Union[int, float]) -> str:
    return f"{value:,}"
