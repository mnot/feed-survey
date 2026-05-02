from datetime import timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import dateutil.parser

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

CORE_NAMESPACES = frozenset(
    {
        "http://www.w3.org/2005/Atom",
        "http://www.w3.org/1999/xhtml",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "http://purl.org/rss/1.0/",
    }
)

ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"


def split_tag(tag: Any) -> Tuple[str, str]:
    """Split a Clark-notation tag {namespace}localname into namespace/local."""
    if isinstance(tag, str) and tag.startswith("{"):
        namespace, local = tag[1:].split("}", 1)
        return namespace, local
    return "", str(tag)


def track_lang(elem: Any, result: Dict[str, Any], entry_level: bool) -> None:
    """Record any xml:lang attribute present on *elem*."""
    lang = elem.get(XML_LANG)
    if lang:
        lang = lang.strip().lower()
        if lang:
            result["all_languages"].add(lang)
            if entry_level:
                result["entry_languages"].add(lang)


def track_extension(elem: Any, result: Dict[str, Any]) -> None:
    namespace, local = split_tag(elem.tag)
    if namespace and namespace not in CORE_NAMESPACES:
        result["extensions"].add((namespace, local))


def update_entry_dates(result: Dict[str, Any], date_value: Optional[List[int]]) -> None:
    """Update both newest_entry_date and oldest_entry_date from *date_value*."""
    if not date_value:
        return
    if not result["newest_entry_date"] or date_value > result["newest_entry_date"]:
        result["newest_entry_date"] = date_value
    if not result["oldest_entry_date"] or date_value < result["oldest_entry_date"]:
        result["oldest_entry_date"] = date_value


def classify_content(seen: Set[str]) -> str:
    if not seen:
        return "unknown"
    types = frozenset(seen)
    if types == {"plain"}:
        return "plain"
    if types == {"html"}:
        return "html"
    if types == {"xhtml"}:
        return "xhtml"
    if len(types) > 1:
        return "mixed"
    return "unknown"


def atom_content_type(type_attr: Optional[str]) -> str:
    type_name = (type_attr or "text").lower().strip()
    if type_name in ("text", "text/plain", ""):
        return "plain"
    if type_name in ("html", "text/html"):
        return "html"
    if type_name in ("xhtml", "application/xhtml+xml"):
        return "xhtml"
    return "plain"


def text_content_type(text: Optional[str]) -> str:
    content = (text or "").strip()
    if "<" in content and ">" in content:
        return "html"
    return "plain"


def parse_date(date_str: Optional[str]) -> Optional[List[int]]:
    if not date_str:
        return None
    try:
        parsed = dateutil.parser.parse(date_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return [
            parsed.year,
            parsed.month,
            parsed.day,
            parsed.hour,
            parsed.minute,
            parsed.second,
            parsed.weekday(),
            0,
            0,
        ]
    except (ValueError, TypeError, OverflowError):
        return None
