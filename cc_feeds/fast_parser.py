import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import dateutil.parser
from lxml import etree

logger = logging.getLogger(__name__)


class FastFeedParser:
    """
    A fast, stream-based feed parser using lxml's iterparse (SAX-like).
    Designed for speed and memory efficiency on large-scale crawls.
    """

    @staticmethod
    def parse(content: bytes) -> Dict[str, Any]:
        """
        Parse a feed from bytes. Returns a dictionary compatible with the
        expected structure in processor.py.
        """
        result = {
            "valid": False,
            "feed": {"title": "", "link": "", "updated_parsed": None, "language": None},
            "entries": [],  # Placeholder for compatibility
            "entries_count": 0,
            "newest_entry_date": None,
            "extensions": set(),
            "has_content": False,
            "has_summary": False,
            "content_lengths": [],
            "entry_languages": set(),
            "error": None,
            "version": "",
        }

        try:
            # Need start and end events
            context = etree.iterparse(
                io.BytesIO(content),
                events=("start", "end"),
                recover=True,
                resolve_entities=False,
            )

            # Detect format on root
            event, root_elem = next(context)
            tag = FastFeedParser._localname(root_elem.tag)

            if tag == "feed":
                result["version"] = "atom10"
                FastFeedParser._parse_atom(context, root_elem, result)
            elif tag == "rss":
                result["version"] = f"rss{root_elem.get('version', '2.0')}"
                FastFeedParser._parse_rss2(context, root_elem, result)
            elif tag == "RDF":
                result["version"] = "rss10"
                FastFeedParser._parse_rss1(context, root_elem, result)
            else:
                # Try to sniff namespaces if root is unknown
                if "rss" in str(root_elem.nsmap.values()).lower():
                    result["version"] = "rss20"
                    FastFeedParser._parse_rss2(context, root_elem, result)
                else:
                    result["error"] = f"Unknown root tag: {tag}"
                    return result

            result["valid"] = True
        except Exception as e:
            result["error"] = str(e)

        return result

    @staticmethod
    def _localname(tag: Any) -> str:
        if isinstance(tag, str) and "}" in tag:
            return tag.split("}", 1)[1]
        return str(tag)

    @staticmethod
    def _parse_atom(context: Any, root: Any, result: Dict[str, Any]) -> None:
        current_entry: Optional[Dict[str, Any]] = None
        for event, elem in context:
            tag = FastFeedParser._localname(elem.tag)

            if event == "start":
                if tag == "entry":
                    current_entry = {}
                    result["entries_count"] += 1
            elif event == "end":
                if current_entry is None:
                    # Global feed info
                    if tag == "title" and not result["feed"]["title"]:
                        result["feed"]["title"] = elem.text or ""
                    elif tag == "link" and not result["feed"]["link"]:
                        result["feed"]["link"] = elem.get("href", "")
                    elif (tag == "updated" or tag == "published") and not result[
                        "feed"
                    ]["updated_parsed"]:
                        result["feed"]["updated_parsed"] = FastFeedParser._parse_date(
                            elem.text
                        )
                    elif tag == "language" and not result["feed"]["language"]:
                        result["feed"]["language"] = elem.text or ""
                else:
                    # Inside an entry
                    if tag == "entry":
                        # Finalize entry
                        dt = current_entry.get("date")
                        if dt:
                            if (
                                not result["newest_entry_date"]
                                or dt > result["newest_entry_date"]
                            ):
                                result["newest_entry_date"] = dt
                        current_entry = None
                    elif tag == "updated" or tag == "published":
                        current_entry["date"] = FastFeedParser._parse_date(elem.text)
                    elif tag == "language":
                        lang = (elem.text or "").lower()
                        if lang:
                            result["entry_languages"].add(lang)
                    elif tag == "content":
                        result["has_content"] = True
                        if elem.text:
                            result["content_lengths"].append(len(elem.text))
                    elif tag == "summary":
                        result["has_summary"] = True
                        if elem.text:
                            result["content_lengths"].append(len(elem.text))

                # Check namespaces for extensions
                for prefix, ns in elem.nsmap.items():
                    if (
                        prefix
                        and ns
                        and ns
                        not in (
                            "http://www.w3.org/2005/Atom",
                            "http://www.w3.org/1999/xhtml",
                        )
                    ):
                        result["extensions"].add(prefix)

                # Clear element to save memory
                if tag != "feed":
                    elem.clear()
                    if elem.getparent() is not None:
                        elem.getparent().remove(elem)

    @staticmethod
    def _parse_rss2(context: Any, root: Any, result: Dict[str, Any]) -> None:
        current_item: Optional[Dict[str, Any]] = None
        for event, elem in context:
            tag = FastFeedParser._localname(elem.tag)

            if event == "start":
                if tag == "item":
                    current_item = {}
                    result["entries_count"] += 1
            elif event == "end":
                if current_item is None:
                    # Global channel info
                    if tag == "title" and not result["feed"]["title"]:
                        result["feed"]["title"] = elem.text or ""
                    elif tag == "link" and not result["feed"]["link"]:
                        result["feed"]["link"] = elem.text or ""
                    elif tag == "lastBuildDate" or tag == "pubDate":
                        if not result["feed"]["updated_parsed"]:
                            result["feed"]["updated_parsed"] = (
                                FastFeedParser._parse_date(elem.text)
                            )
                    elif tag == "language" and not result["feed"]["language"]:
                        result["feed"]["language"] = elem.text or ""
                else:
                    if tag == "item":
                        dt = current_item.get("date")
                        if dt:
                            if (
                                not result["newest_entry_date"]
                                or dt > result["newest_entry_date"]
                            ):
                                result["newest_entry_date"] = dt
                        current_item = None
                    elif tag == "pubDate":
                        current_item["date"] = FastFeedParser._parse_date(elem.text)
                    elif tag == "description":
                        result["has_summary"] = True
                        if elem.text:
                            result["content_lengths"].append(len(elem.text))
                    elif tag == "encoded" and "content" in elem.tag:
                        result["has_content"] = True
                        if elem.text:
                            result["content_lengths"].append(len(elem.text))

                for prefix, ns in elem.nsmap.items():
                    if prefix and ns:
                        result["extensions"].add(prefix)

                if tag != "rss" and tag != "channel":
                    elem.clear()
                    if elem.getparent() is not None:
                        elem.getparent().remove(elem)

    @staticmethod
    def _parse_rss1(context: Any, root: Any, result: Dict[str, Any]) -> None:
        current_item: Optional[Dict[str, Any]] = None
        for event, elem in context:
            tag = FastFeedParser._localname(elem.tag)
            if event == "start":
                if tag == "item":
                    current_item = {}
                    result["entries_count"] += 1
            elif event == "end":
                if current_item is None:
                    if tag == "title" and not result["feed"]["title"]:
                        result["feed"]["title"] = elem.text or ""
                    elif tag == "link" and not result["feed"]["link"]:
                        result["feed"]["link"] = elem.text or ""
                    elif tag == "date":
                        if not result["feed"]["updated_parsed"]:
                            result["feed"]["updated_parsed"] = (
                                FastFeedParser._parse_date(elem.text)
                            )
                else:
                    if tag == "item":
                        dt = current_item.get("date")
                        if dt:
                            if (
                                not result["newest_entry_date"]
                                or dt > result["newest_entry_date"]
                            ):
                                result["newest_entry_date"] = dt
                        current_item = None
                    elif tag == "date":
                        current_item["date"] = FastFeedParser._parse_date(elem.text)
                    elif tag == "description":
                        result["has_summary"] = True

                for prefix, ns in elem.nsmap.items():
                    if prefix and ns:
                        result["extensions"].add(prefix)

                if tag != "RDF":
                    elem.clear()

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[List[int]]:
        if not date_str:
            return None
        try:
            dt = dateutil.parser.parse(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return [
                dt.year,
                dt.month,
                dt.day,
                dt.hour,
                dt.minute,
                dt.second,
                dt.weekday(),
                0,
                0,
            ]
        except Exception:
            return None
