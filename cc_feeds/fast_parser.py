import io
import logging
from datetime import timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import dateutil.parser
from lxml import etree

logger = logging.getLogger(__name__)

# xml:lang attribute Clark-notation name
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# Namespaces that are considered "core" and should not be reported as extensions
_CORE_NS = frozenset(
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


class FastFeedParser:
    """
    A fast, stream-based feed parser using lxml's iterparse (SAX-like).
    Designed for speed and memory efficiency on large-scale crawls.
    Supports Atom 1.0, RSS 2.0, and RSS 1.0 (RDF).
    """

    @staticmethod
    def parse(content: bytes) -> Dict[str, Any]:
        """
        Parse a feed from bytes.  Returns a result dict with:
          valid, version, feed, entries_count, newest_entry_date,
          oldest_entry_date, extensions (set of (ns_uri, localname) tuples),
          has_content, has_summary, content_type_profile
          (plain/html/xhtml/mixed/unknown), content_lengths, all_languages,
          entry_languages, error.
        """
        result: Dict[str, Any] = {
            "valid": False,
            "version": "",
            "feed": {"title": "", "link": "", "updated_parsed": None, "language": None},
            "entries_count": 0,
            "newest_entry_date": None,
            "oldest_entry_date": None,
            "extensions": set(),          # set of (namespace_uri, localname) tuples
            "has_content": False,
            "has_summary": False,
            "content_type_profile": "unknown",  # plain / html / xhtml / mixed / unknown
            "content_lengths": [],
            "all_languages": set(),        # every xml:lang value seen anywhere in the doc
            "entry_languages": set(),      # xml:lang values seen inside entries/items
            "error": None,
            # Internal accumulator – removed before returning
            "_content_types_seen": set(),
        }

        # Quick sanity check: real XML/feed content starts with '<' (possibly
        # after a BOM or whitespace).  Binary or non-XML responses that slipped
        # through the content-type filter would cause lxml's recovery mode to
        # spin for minutes trying to find XML structure in garbage bytes.
        stripped = content.lstrip()
        if not stripped or stripped[0:1] not in (b"<", b"\xef"):  # '<' or UTF-8 BOM
            result["error"] = "Not XML"
            result.pop("_content_types_seen", None)
            return result

        try:
            context = etree.iterparse(
                io.BytesIO(content),
                events=("start", "end"),
                recover=False,
                resolve_entities=False,
            )

            event, root_elem = next(context)
            ns, local = FastFeedParser._ns(root_elem.tag)

            # Capture any xml:lang on the root element immediately
            FastFeedParser._track_lang(root_elem, result, entry_level=False)

            if local == "feed" and (ns == ATOM_NS or ns == ""):
                result["version"] = "atom10"
                # For Atom, xml:lang on the root <feed> is the feed-level language
                root_lang = root_elem.get(XML_LANG)
                if root_lang:
                    result["feed"]["language"] = root_lang.strip().lower()
                FastFeedParser._parse_atom(context, root_elem, result)
            elif local == "rss":
                result["version"] = f"rss{root_elem.get('version', '2.0')}"
                FastFeedParser._parse_rss2(context, root_elem, result)
            elif local == "RDF":
                result["version"] = "rss10"
                FastFeedParser._parse_rss1(context, root_elem, result)
            else:
                result["error"] = f"Unknown root tag: {local}"
                result.pop("_content_types_seen", None)
                return result

            result["content_type_profile"] = FastFeedParser._classify_content(
                result["_content_types_seen"]
            )
            result["valid"] = True

        except StopIteration:
            result["error"] = "Empty document"
        except Exception as exc:
            result["error"] = str(exc)

        result.pop("_content_types_seen", None)
        return result

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _ns(tag: Any) -> Tuple[str, str]:
        """Split a Clark-notation tag {namespace}localname → (namespace, localname)."""
        if isinstance(tag, str) and tag.startswith("{"):
            ns, local = tag[1:].split("}", 1)
            return ns, local
        return "", str(tag)

    @staticmethod
    def _track_lang(elem: Any, result: Dict[str, Any], entry_level: bool) -> None:
        """Record any xml:lang attribute present on *elem*."""
        lang = elem.get(XML_LANG)
        if lang:
            lang = lang.strip().lower()
            if lang:
                result["all_languages"].add(lang)
                if entry_level:
                    result["entry_languages"].add(lang)

    @staticmethod
    def _track_ext(elem: Any, result: Dict[str, Any]) -> None:
        """
        If *elem* belongs to a non-core namespace, record (namespace_uri, localname)
        as an extension.
        """
        ns, local = FastFeedParser._ns(elem.tag)
        if ns and ns not in _CORE_NS:
            result["extensions"].add((ns, local))

    @staticmethod
    def _update_entry_dates(result: Dict[str, Any], dt: Optional[List[int]]) -> None:
        """Update both newest_entry_date and oldest_entry_date from *dt*."""
        if not dt:
            return
        if not result["newest_entry_date"] or dt > result["newest_entry_date"]:
            result["newest_entry_date"] = dt
        if not result["oldest_entry_date"] or dt < result["oldest_entry_date"]:
            result["oldest_entry_date"] = dt

    @staticmethod
    def _classify_content(seen: Set[str]) -> str:
        """
        Given the set of content-type tokens encountered (plain/html/xhtml),
        return a profile string.
        """
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

    @staticmethod
    def _atom_content_type(type_attr: Optional[str]) -> str:
        """Map an Atom ``type`` attribute value to our content-type token."""
        t = (type_attr or "text").lower().strip()
        if t in ("text", "text/plain", ""):
            return "plain"
        if t in ("html", "text/html"):
            return "html"
        if t == "xhtml":
            return "xhtml"
        return "plain"

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[List[int]]:
        if not date_str:
            return None
        try:
            dt = dateutil.parser.parse(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return [
                dt.year, dt.month, dt.day,
                dt.hour, dt.minute, dt.second,
                dt.weekday(), 0, 0,
            ]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Format-specific parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_atom(context: Any, root: Any, result: Dict[str, Any]) -> None:
        current_entry: Optional[Dict[str, Any]] = None

        for event, elem in context:
            ns, local = FastFeedParser._ns(elem.tag)

            if event == "start":
                in_entry = current_entry is not None
                if local == "entry" and ns == ATOM_NS:
                    current_entry = {}
                    result["entries_count"] += 1
                    FastFeedParser._track_lang(elem, result, entry_level=True)
                else:
                    FastFeedParser._track_lang(elem, result, entry_level=in_entry)

            elif event == "end":
                FastFeedParser._track_ext(elem, result)

                if current_entry is None:
                    # Feed-level elements
                    if ns == ATOM_NS:
                        if local == "title" and not result["feed"]["title"]:
                            result["feed"]["title"] = (elem.text or "").strip()
                        elif local == "link" and not result["feed"]["link"]:
                            result["feed"]["link"] = elem.get("href", "")
                        elif local in ("updated", "published") and not result["feed"]["updated_parsed"]:
                            result["feed"]["updated_parsed"] = FastFeedParser._parse_date(elem.text)
                    elif ns == DC_NS and local == "language" and not result["feed"]["language"]:
                        result["feed"]["language"] = (elem.text or "").strip().lower()
                else:
                    # Entry-level
                    if local == "entry" and ns == ATOM_NS:
                        FastFeedParser._update_entry_dates(result, current_entry.get("date"))
                        current_entry = None
                    elif ns == ATOM_NS:
                        if local in ("updated", "published"):
                            d = FastFeedParser._parse_date(elem.text)
                            if d and not current_entry.get("date"):
                                current_entry["date"] = d
                        elif local == "content":
                            result["has_content"] = True
                            ctype = FastFeedParser._atom_content_type(elem.get("type"))
                            result["_content_types_seen"].add(ctype)
                            text = elem.text or ""
                            if text:
                                result["content_lengths"].append(len(text))
                        elif local == "summary":
                            result["has_summary"] = True
                            text = elem.text or ""
                            if text:
                                result["content_lengths"].append(len(text))

                if local != "feed":
                    try:
                        elem.clear()
                        parent = elem.getparent()
                        if parent is not None:
                            parent.remove(elem)
                    except Exception:
                        pass

    @staticmethod
    def _parse_rss2(context: Any, root: Any, result: Dict[str, Any]) -> None:
        current_item: Optional[Dict[str, Any]] = None

        for event, elem in context:
            ns, local = FastFeedParser._ns(elem.tag)

            if event == "start":
                in_item = current_item is not None
                if local == "item" and ns == "":
                    current_item = {}
                    result["entries_count"] += 1
                    FastFeedParser._track_lang(elem, result, entry_level=True)
                else:
                    FastFeedParser._track_lang(elem, result, entry_level=in_item)

            elif event == "end":
                FastFeedParser._track_ext(elem, result)

                if current_item is None:
                    # Channel-level
                    if ns == "":
                        if local == "title" and not result["feed"]["title"]:
                            result["feed"]["title"] = (elem.text or "").strip()
                        elif local == "link" and not result["feed"]["link"]:
                            result["feed"]["link"] = (elem.text or "").strip()
                        elif local in ("lastBuildDate", "pubDate") and not result["feed"]["updated_parsed"]:
                            result["feed"]["updated_parsed"] = FastFeedParser._parse_date(elem.text)
                        elif local == "language" and not result["feed"]["language"]:
                            result["feed"]["language"] = (elem.text or "").strip().lower()
                    elif ns == DC_NS:
                        if local == "language" and not result["feed"]["language"]:
                            result["feed"]["language"] = (elem.text or "").strip().lower()
                else:
                    if local == "item" and ns == "":
                        FastFeedParser._update_entry_dates(result, current_item.get("date"))
                        current_item = None
                    elif ns == "":
                        if local == "pubDate":
                            d = FastFeedParser._parse_date(elem.text)
                            if d and not current_item.get("date"):
                                current_item["date"] = d
                        elif local == "description":
                            # RSS 2.0 <description> is implicitly HTML per the spec
                            result["has_summary"] = True
                            result["_content_types_seen"].add("html")
                            text = elem.text or ""
                            if text:
                                result["content_lengths"].append(len(text))
                    elif ns == DC_NS:
                        if local == "date":
                            d = FastFeedParser._parse_date(elem.text)
                            if d and not current_item.get("date"):
                                current_item["date"] = d
                    elif ns == CONTENT_NS:
                        if local == "encoded":
                            result["has_content"] = True
                            result["_content_types_seen"].add("html")
                            text = elem.text or ""
                            if text:
                                result["content_lengths"].append(len(text))

                if local not in ("rss", "channel"):
                    try:
                        elem.clear()
                        parent = elem.getparent()
                        if parent is not None:
                            parent.remove(elem)
                    except Exception:
                        pass

    @staticmethod
    def _parse_rss1(context: Any, root: Any, result: Dict[str, Any]) -> None:
        current_item: Optional[Dict[str, Any]] = None

        for event, elem in context:
            ns, local = FastFeedParser._ns(elem.tag)

            if event == "start":
                in_item = current_item is not None
                if local == "item":
                    current_item = {}
                    result["entries_count"] += 1
                    FastFeedParser._track_lang(elem, result, entry_level=True)
                else:
                    FastFeedParser._track_lang(elem, result, entry_level=in_item)

            elif event == "end":
                FastFeedParser._track_ext(elem, result)

                if current_item is None:
                    # Channel-level
                    if local == "title" and not result["feed"]["title"]:
                        result["feed"]["title"] = (elem.text or "").strip()
                    elif local == "link" and not result["feed"]["link"]:
                        result["feed"]["link"] = (elem.text or "").strip()
                    elif ns == DC_NS:
                        if local == "date" and not result["feed"]["updated_parsed"]:
                            result["feed"]["updated_parsed"] = FastFeedParser._parse_date(elem.text)
                        elif local == "language" and not result["feed"]["language"]:
                            result["feed"]["language"] = (elem.text or "").strip().lower()
                else:
                    if local == "item":
                        FastFeedParser._update_entry_dates(result, current_item.get("date"))
                        current_item = None
                    elif ns == DC_NS and local == "date":
                        d = FastFeedParser._parse_date(elem.text)
                        if d and not current_item.get("date"):
                            current_item["date"] = d
                    elif local == "description":
                        result["has_summary"] = True
                        result["_content_types_seen"].add("html")
                        text = elem.text or ""
                        if text:
                            result["content_lengths"].append(len(text))
                    elif ns == CONTENT_NS and local == "encoded":
                        result["has_content"] = True
                        result["_content_types_seen"].add("html")
                        text = elem.text or ""
                        if text:
                            result["content_lengths"].append(len(text))

                if local != "RDF":
                    try:
                        elem.clear()
                        parent = elem.getparent()
                        if parent is not None:
                            parent.remove(elem)
                    except Exception:
                        pass
