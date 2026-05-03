import re
from typing import Any, Iterable, Mapping, Set

KNOWN_PLATFORM_PATTERNS = {
    "blogger": ("blogger", "blogspot"),
    "drupal": ("drupal",),
    "feedburner": ("feedburner",),
    "ghost": ("ghost",),
    "joomla": ("joomla",),
    "medium": ("medium",),
    "shopify": ("shopify",),
    "squarespace": ("squarespace",),
    "substack": ("substack",),
    "wordpress": ("wordpress", "wp.com"),
}

HEADER_FIELDS = (
    "Server",
    "X-Generator",
    "X-Powered-By",
    "X-Drupal-Cache",
    "X-Drupal-Dynamic-Cache",
)

_META_GENERATOR_RE = re.compile(
    rb"<meta\s+[^>]*name\s*=\s*['\"]generator['\"][^>]*content\s*=\s*['\"]([^'\"]+)",
    re.IGNORECASE,
)

HTML_MARKERS = {
    "drupal": (b"/sites/default/files/", b"drupal-settings-json"),
    "ghost": (b"ghost/content/", b"ghost.org"),
    "shopify": (b"cdn.shopify.com", b"shopify.theme"),
    "squarespace": (b"static1.squarespace.com", b"squarespace-cdn.com"),
    "substack": (b"substackcdn.com", b"substack.com"),
    "wix": (b"static.wixstatic.com", b"wix-code-sdk"),
    "wordpress": (b"/wp-content/", b"/wp-includes/"),
}


def fingerprint_http_headers(headers: Mapping[str, Any]) -> Set[str]:
    fingerprints: Set[str] = set()
    values = [_header_value(headers, header) for header in HEADER_FIELDS]
    fingerprints.update(_fingerprints_from_values(value for value in values if value))
    return fingerprints


def fingerprint_feed_generator(generator: Any) -> Set[str]:
    return _fingerprints_from_values([str(generator or "")])


def fingerprint_html(content: bytes) -> Set[str]:
    fingerprints: Set[str] = set()
    match = _META_GENERATOR_RE.search(content[:32768])
    if match:
        fingerprints.update(
            _fingerprints_from_values([match.group(1).decode("utf-8", "ignore")])
        )

    normalized = content[:32768].lower()
    for label, markers in HTML_MARKERS.items():
        if any(marker in normalized for marker in markers):
            fingerprints.add(label)
    return fingerprints


def _fingerprints_from_values(values: Iterable[str]) -> Set[str]:
    fingerprints: Set[str] = set()
    for value in values:
        normalized = value.lower()
        for label, patterns in KNOWN_PLATFORM_PATTERNS.items():
            if any(pattern in normalized for pattern in patterns):
                fingerprints.add(label)
    return fingerprints


def _header_value(headers: Mapping[str, Any], name: str) -> str:
    value = headers.get(name)
    if value is not None:
        return str(value)
    lower_name = name.lower()
    for header_name, header_value in headers.items():
        if str(header_name).lower() == lower_name:
            return str(header_value)
    return ""
