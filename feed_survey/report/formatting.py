from typing import Any, Dict, Optional, Union

_NS_PREFIXES: Dict[str, str] = {
    "http://purl.org/dc/elements/1.1/": "dc",
    "http://purl.org/dc/terms/": "dcterms",
    "http://search.yahoo.com/mrss/": "media",
    "http://purl.org/rss/1.0/modules/content/": "content",
    "http://purl.org/rss/1.0/modules/slash/": "slash",
    "http://purl.org/rss/1.0/modules/syndication/": "sy",
    "http://purl.org/syndication/thread/1.0": "thr",
    "http://purl.org/syndication/thread/1.0#": "thr",
    "http://a9.com/-/spec/opensearchrss/1.0/": "opensearch",
    "http://www.w3.org/2003/01/geo/wgs84_pos#": "geo",
    "http://www.georss.org/georss/": "georss",
    "http://schemas.google.com/g/2005": "gd",
    "http://schemas.google.com/g/2005#": "gd",
    "http://www.itunes.com/dtds/podcast-1.0.dtd": "itunes",
    "http://wellformedweb.org/CommentAPI/": "wfw",
    "http://webfeeds.org/rss/1.0": "webfeeds",
    "http://purl.org/rss/1.0/modules/company/": "co",
    "http://purl.org/rss/1.0/modules/event/": "ev",
}

_PREFIX_SPECS: Dict[str, str] = {
    "co": "http://web.resource.org/rss/1.0/modules/company/",
    "content": "https://web.resource.org/rss/1.0/modules/content/",
    "dc": "https://www.dublincore.org/specifications/dublin-core/dces/",
    "dcterms": "https://www.dublincore.org/specifications/dublin-core/dcmi-terms/",
    "ev": "http://web.resource.org/rss/1.0/modules/event/",
    "gd": "https://developers.google.com/gdata/docs/1.0/elements",
    "geo": "https://www.w3.org/2003/01/geo/",
    "georss": "https://www.ogc.org/publications/standard/georss/",
    "itunes": "https://podcasters.apple.com/support/823-podcast-requirements",
    "media": "https://www.rssboard.org/media-rss",
    "opensearch": "https://github.com/dewitt/opensearch/blob/master/opensearch-1-1-draft-6.md",
    "slash": "http://web.resource.org/rss/1.0/modules/slash/",
    "sy": "https://web.resource.org/rss/1.0/modules/syndication/",
    "thr": "https://www.rfc-editor.org/rfc/rfc4685.html",
    "webfeeds": "https://webfeeds.org/rss/1.0",
    "wfw": "https://www.rssboard.org/comment-api",
}


def format_extension(ext: Any) -> str:
    """Format a (namespace_uri, localname) tuple as a readable prefix:local string."""
    if isinstance(ext, (tuple, list)) and len(ext) == 2:
        ns, local = str(ext[0]), str(ext[1])
        prefix = _NS_PREFIXES.get(ns)
        if prefix:
            return f"{prefix}:{local}"
        separator = "" if ns.endswith(("/", "#")) else "#"
        return f"{ns}{separator}{local}"
    return str(ext)


def extension_link_parts(label: str) -> Optional[Dict[str, str]]:
    """Return link metadata for a compact namespace prefix label."""
    prefix, separator, local = label.partition(":")
    if not separator or not local:
        return None

    href = _PREFIX_SPECS.get(prefix)
    if not href:
        return None
    return {
        "extension_prefix": prefix,
        "extension_local": local,
        "extension_href": href,
    }


def format_number(value: Union[int, float]) -> str:
    return f"{value:,}"
