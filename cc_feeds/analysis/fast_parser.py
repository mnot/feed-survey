import io
import logging
from typing import Any, Dict, Optional

from lxml import etree

from cc_feeds.analysis.feed_helpers import (
    ATOM_NS,
    CONTENT_NS,
    DC_NS,
    XML_LANG,
    atom_content_type,
    classify_content,
    parse_date,
    split_tag,
    track_extension,
    track_lang,
    update_entry_dates,
)

logger = logging.getLogger(__name__)


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
            "extensions": set(),  # set of (namespace_uri, localname) tuples
            "has_content": False,
            "has_summary": False,
            "content_type_profile": "unknown",  # plain / html / xhtml / mixed / unknown
            "content_lengths": [],
            "all_languages": set(),  # every xml:lang value seen anywhere in the doc
            "entry_languages": set(),  # xml:lang values seen inside entries/items
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
            context = etree.iterparse(  # pylint: disable=c-extension-no-member
                io.BytesIO(content),
                events=("start", "end"),
                recover=False,
                resolve_entities=False,
                no_network=True,  # never fetch external DTDs or entities
                load_dtd=False,  # don't load DTDs at all
                dtd_validation=False,  # don't validate against DTD
            )

            _event, root_elem = next(context)
            ns, local = split_tag(root_elem.tag)

            # Capture any xml:lang on the root element immediately
            track_lang(root_elem, result, entry_level=False)

            if local == "feed" and ns in (ATOM_NS, ""):
                result["version"] = "atom10"
                # For Atom, xml:lang on the root <feed> is the feed-level language
                root_lang = root_elem.get(XML_LANG)
                if root_lang:
                    result["feed"]["language"] = root_lang.strip().lower()
                FastFeedParser._parse_atom(context, result)
            elif local == "rss":
                result["version"] = f"rss{root_elem.get('version', '2.0')}"
                FastFeedParser._parse_rss2(context, result)
            elif local == "RDF":
                result["version"] = "rss10"
                FastFeedParser._parse_rss1(context, result)
            else:
                result["error"] = f"Unknown root tag: {local}"
                result.pop("_content_types_seen", None)
                return result

            result["content_type_profile"] = classify_content(
                result["_content_types_seen"]
            )
            result["valid"] = True

        except StopIteration:
            result["error"] = "Empty document"
        except (SyntaxError, TypeError, ValueError) as exc:
            result["error"] = str(exc)

        result.pop("_content_types_seen", None)
        return result

    @staticmethod
    def _parse_atom(context: Any, result: Dict[str, Any]) -> None:
        current_entry: Optional[Dict[str, Any]] = None

        for event, elem in context:
            ns, local = split_tag(elem.tag)

            if event == "start":
                in_entry = current_entry is not None
                if local == "entry" and ns == ATOM_NS:
                    current_entry = {}
                    result["entries_count"] += 1
                    track_lang(elem, result, entry_level=True)
                else:
                    track_lang(elem, result, entry_level=in_entry)

            elif event == "end":
                track_extension(elem, result)

                if current_entry is None:
                    FastFeedParser._handle_atom_feed_end(ns, local, elem, result)
                else:
                    if local == "entry" and ns == ATOM_NS:
                        update_entry_dates(result, current_entry.get("date"))
                        current_entry = None
                    else:
                        FastFeedParser._handle_atom_entry_end(
                            ns, local, elem, current_entry, result
                        )

                FastFeedParser._clear_element(elem, keep_local_names={"feed"})

    @staticmethod
    def _parse_rss2(context: Any, result: Dict[str, Any]) -> None:
        current_item: Optional[Dict[str, Any]] = None

        for event, elem in context:
            ns, local = split_tag(elem.tag)

            if event == "start":
                in_item = current_item is not None
                if local == "item" and ns == "":
                    current_item = {}
                    result["entries_count"] += 1
                    track_lang(elem, result, entry_level=True)
                else:
                    track_lang(elem, result, entry_level=in_item)

            elif event == "end":
                track_extension(elem, result)

                if current_item is None:
                    FastFeedParser._handle_rss2_channel_end(ns, local, elem, result)
                else:
                    if local == "item" and ns == "":
                        update_entry_dates(result, current_item.get("date"))
                        current_item = None
                    else:
                        FastFeedParser._handle_rss2_item_end(
                            ns, local, elem, current_item, result
                        )

                FastFeedParser._clear_element(elem, keep_local_names={"rss", "channel"})

    @staticmethod
    def _parse_rss1(context: Any, result: Dict[str, Any]) -> None:
        current_item: Optional[Dict[str, Any]] = None

        for event, elem in context:
            ns, local = split_tag(elem.tag)

            if event == "start":
                in_item = current_item is not None
                if local == "item":
                    current_item = {}
                    result["entries_count"] += 1
                    track_lang(elem, result, entry_level=True)
                else:
                    track_lang(elem, result, entry_level=in_item)

            elif event == "end":
                track_extension(elem, result)

                if current_item is None:
                    FastFeedParser._handle_rss1_channel_end(ns, local, elem, result)
                else:
                    if local == "item":
                        update_entry_dates(result, current_item.get("date"))
                        current_item = None
                    else:
                        FastFeedParser._handle_rss1_item_end(
                            ns, local, elem, current_item, result
                        )

                FastFeedParser._clear_element(elem, keep_local_names={"RDF"})

    @staticmethod
    def _handle_atom_feed_end(
        ns: str, local: str, elem: Any, result: Dict[str, Any]
    ) -> None:
        if ns == ATOM_NS:
            if local == "title" and not result["feed"]["title"]:
                result["feed"]["title"] = (elem.text or "").strip()
            elif local == "link" and not result["feed"]["link"]:
                result["feed"]["link"] = elem.get("href", "")
            elif (
                local in ("updated", "published")
                and not result["feed"]["updated_parsed"]
            ):
                result["feed"]["updated_parsed"] = parse_date(elem.text)
        elif ns == DC_NS and local == "language" and not result["feed"]["language"]:
            result["feed"]["language"] = (elem.text or "").strip().lower()

    @staticmethod
    def _handle_atom_entry_end(
        ns: str,
        local: str,
        elem: Any,
        current_entry: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        if ns != ATOM_NS:
            return
        if local in ("updated", "published"):
            FastFeedParser._set_entry_date(current_entry, elem.text)
        elif local == "content":
            result["has_content"] = True
            result["_content_types_seen"].add(atom_content_type(elem.get("type")))
            FastFeedParser._remember_text_length(elem, result)
        elif local == "summary":
            result["has_summary"] = True
            FastFeedParser._remember_text_length(elem, result)

    @staticmethod
    def _handle_rss2_channel_end(
        ns: str, local: str, elem: Any, result: Dict[str, Any]
    ) -> None:
        if ns == "":
            if local == "title" and not result["feed"]["title"]:
                result["feed"]["title"] = (elem.text or "").strip()
            elif local == "link" and not result["feed"]["link"]:
                result["feed"]["link"] = (elem.text or "").strip()
            elif (
                local in ("lastBuildDate", "pubDate")
                and not result["feed"]["updated_parsed"]
            ):
                result["feed"]["updated_parsed"] = parse_date(elem.text)
            elif local == "language" and not result["feed"]["language"]:
                result["feed"]["language"] = (elem.text or "").strip().lower()
        elif ns == DC_NS and local == "language" and not result["feed"]["language"]:
            result["feed"]["language"] = (elem.text or "").strip().lower()

    @staticmethod
    def _handle_rss2_item_end(
        ns: str,
        local: str,
        elem: Any,
        current_item: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        if ns == "" and local == "pubDate":
            FastFeedParser._set_entry_date(current_item, elem.text)
        elif ns == "" and local == "description":
            result["has_summary"] = True
            result["_content_types_seen"].add("html")
            FastFeedParser._remember_text_length(elem, result)
        elif ns == DC_NS and local == "date":
            FastFeedParser._set_entry_date(current_item, elem.text)
        elif ns == CONTENT_NS and local == "encoded":
            result["has_content"] = True
            result["_content_types_seen"].add("html")
            FastFeedParser._remember_text_length(elem, result)

    @staticmethod
    def _handle_rss1_channel_end(
        ns: str, local: str, elem: Any, result: Dict[str, Any]
    ) -> None:
        if local == "title" and not result["feed"]["title"]:
            result["feed"]["title"] = (elem.text or "").strip()
        elif local == "link" and not result["feed"]["link"]:
            result["feed"]["link"] = (elem.text or "").strip()
        elif ns == DC_NS and local == "date" and not result["feed"]["updated_parsed"]:
            result["feed"]["updated_parsed"] = parse_date(elem.text)
        elif ns == DC_NS and local == "language" and not result["feed"]["language"]:
            result["feed"]["language"] = (elem.text or "").strip().lower()

    @staticmethod
    def _handle_rss1_item_end(
        ns: str,
        local: str,
        elem: Any,
        current_item: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        if ns == DC_NS and local == "date":
            FastFeedParser._set_entry_date(current_item, elem.text)
        elif local == "description":
            result["has_summary"] = True
            result["_content_types_seen"].add("html")
            FastFeedParser._remember_text_length(elem, result)
        elif ns == CONTENT_NS and local == "encoded":
            result["has_content"] = True
            result["_content_types_seen"].add("html")
            FastFeedParser._remember_text_length(elem, result)

    @staticmethod
    def _set_entry_date(entry: Dict[str, Any], text: Optional[str]) -> None:
        parsed_date = parse_date(text)
        if parsed_date and not entry.get("date"):
            entry["date"] = parsed_date

    @staticmethod
    def _remember_text_length(elem: Any, result: Dict[str, Any]) -> None:
        text = elem.text or ""
        if text:
            result["content_lengths"].append(len(text))

    @staticmethod
    def _clear_element(elem: Any, keep_local_names: set[str]) -> None:
        _ns, local = split_tag(elem.tag)
        if local in keep_local_names:
            return
        try:
            elem.clear()
            parent = elem.getparent()
            if parent is not None:
                parent.remove(elem)
        except (AttributeError, TypeError):
            pass
