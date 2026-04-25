import logging
import pickle
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, cast
from urllib.parse import urljoin

import dateutil.parser
import feedparser
import lxml.html
from fastwarc.warc import WarcRecordType  # pylint: disable=no-name-in-module
from lxml import etree

try:
    from .utils import get_domain, get_tranco_list, normalize_url
except (ImportError, ValueError):
    from utils import get_domain, get_tranco_list, normalize_url  # type: ignore

logger = logging.getLogger(__name__)


class Stats:
    def __init__(self) -> None:
        self.pages_seen: int = 0
        self.sites_seen: Set[str] = set()
        self.autodiscovery_links: Dict[str, List[str]] = (
            {}
        )  # feed_url -> list of page_urls
        self.feed_results: Dict[str, Any] = {}  # feed_url -> info_dict
        self.error_types: Dict[str, int] = {}
        self.top_n: Optional[int] = None
        self.max_crawl_time: Optional[datetime] = None

    def merge(self, other: "Stats") -> None:
        """Merge another Stats object into this one."""
        self.pages_seen += other.pages_seen
        self.sites_seen.update(other.sites_seen)

        for feed_url, pages in other.autodiscovery_links.items():
            if feed_url not in self.autodiscovery_links:
                self.autodiscovery_links[feed_url] = []
            self.autodiscovery_links[feed_url].extend(pages)

        self.feed_results.update(other.feed_results)

        for err_type, count in other.error_types.items():
            self.error_types[err_type] = self.error_types.get(err_type, 0) + count

        other_top_n = getattr(other, "top_n", None)
        if other_top_n is not None:
            if self.top_n is None or other_top_n > self.top_n:
                self.top_n = other_top_n

        other_max_crawl = getattr(other, "max_crawl_time", None)
        if other_max_crawl:
            if not self.max_crawl_time or other_max_crawl > self.max_crawl_time:
                self.max_crawl_time = other_max_crawl

    def save(self, path: str) -> None:
        with open(path, "wb") as f_out:
            pickle.dump(self, f_out)

    @classmethod
    def load(cls, path: str) -> "Stats":
        with open(path, "rb") as f_in:
            return cast(Stats, pickle.load(f_in))


class WarcProcessor:
    def __init__(self, top_n: Optional[int] = None) -> None:
        self.top_n_domains: Optional[Set[str]] = (
            get_tranco_list(top_n) if top_n else None
        )
        self.stats: Stats = Stats()
        self.stats.top_n = top_n

    def get_domain(self, url: str) -> str:
        return get_domain(url)

    def is_in_scope(self, url: str) -> bool:
        if not self.top_n_domains:
            return True
        domain = self.get_domain(url)
        # Check domain and subdomains if necessary, but Tranco is usually just domains
        return (
            domain in self.top_n_domains
            or domain.split(".", 1)[-1] in self.top_n_domains
        )

    def process_record(self, record: Any) -> None:
        if record.record_type != WarcRecordType.response:
            return

        url: Optional[str] = record.headers.get("WARC-Target-URI")
        request_time_str = record.headers.get("WARC-Date")
        if request_time_str:
            request_time = dateutil.parser.parse(request_time_str)
            if request_time.tzinfo is None:
                request_time = request_time.replace(tzinfo=timezone.utc)
            if (
                not self.stats.max_crawl_time
                or request_time > self.stats.max_crawl_time
            ):
                self.stats.max_crawl_time = request_time

        if not url or not self.is_in_scope(url):
            return

        status_code: int = record.http_headers.status_code
        content_type: str = record.http_headers.get("Content-Type", "").lower()

        # Update general stats
        self.stats.pages_seen += 1
        self.stats.sites_seen.add(self.get_domain(url))

        # Check for HTML to find autodiscovery
        if "text/html" in content_type:
            self._process_html(record, url)

        # Check if this record itself is a feed (maybe it was directly linked or just crawled)
        if (
            "application/rss+xml" in content_type
            or "application/atom+xml" in content_type
            or "application/xml" in content_type
            or "text/xml" in content_type
        ):
            self._process_feed(record, url, status_code)

    def _process_html(self, record: Any, url: str) -> None:
        try:
            # Only read the beginning of the file for autodiscovery links
            # as they are always in the <head>
            content = record.reader.read(65536)
            doc = lxml.html.fromstring(content)
            links = doc.xpath('//link[@rel="alternate"]')
            if not isinstance(links, list):
                return

            found_autodiscovery = False
            for link in links:
                if not isinstance(
                    link, etree._Element
                ):  # pylint: disable=protected-access
                    continue
                link_type = str(link.get("type", "")).lower()
                if "rss+xml" not in link_type and "atom+xml" not in link_type:
                    continue

                href = link.get("href")
                if not href:
                    continue

                feed_url = urljoin(url, str(href))
                found_autodiscovery = True
                if feed_url not in self.stats.autodiscovery_links:
                    self.stats.autodiscovery_links[feed_url] = []
                self.stats.autodiscovery_links[feed_url].append(url)

            if found_autodiscovery:
                pass  # We'll calculate this in reporting
        except (
            ValueError,
            TypeError,
            lxml.etree.LxmlError,
        ):  # pylint: disable=no-member
            pass

    def _guess_format(self, content: bytes) -> str:
        """Fallback format detection if feedparser fails."""
        try:
            sniff = content[:1000].decode("utf-8", "ignore").lower()
            if "<rss" in sniff:
                return "rss"
            if "<feed" in sniff and 'xmlns="http://www.w3.org/2005/atom"' in sniff:
                return "atom"
            if "<rdf" in sniff:
                return "rdf"
        except (UnicodeDecodeError, AttributeError):
            pass
        return "unknown"

    def _process_feed(self, record: Any, url: str, status_code: int) -> None:
        request_time_str = record.headers.get("WARC-Date")
        if request_time_str:
            request_time = dateutil.parser.parse(request_time_str)
            if request_time.tzinfo is None:
                request_time = request_time.replace(tzinfo=timezone.utc)
        else:
            request_time = datetime.now(timezone.utc)

        url = normalize_url(url)
        feed_info = self._init_feed_info(status_code, request_time)

        if not 200 <= status_code < 400:
            self.stats.feed_results[url] = feed_info
            return

        try:
            content = record.reader.read()
            parsed_data = feedparser.parse(content)

            if parsed_data.bozo:
                self._handle_bozo(parsed_data)

            # Try to get language from HTTP headers if not in feed
            lang_header = record.http_headers.get("Content-Language")
            if lang_header:
                feed_info["languages"].add(lang_header.split(",")[0].strip())

            if not parsed_data.bozo or parsed_data.entries:
                self._analyze_parsed_feed(feed_info, parsed_data, content, request_time)
            else:
                self._handle_unparsable(feed_info, parsed_data)

        except Exception as exc:  # pylint: disable=broad-except
            self._handle_process_error(feed_info, url, exc)

        self.stats.feed_results[url] = feed_info

    def _init_feed_info(
        self, status_code: int, request_time: datetime
    ) -> Dict[str, Any]:
        return {
            "status": status_code,
            "valid": False,
            "format": None,
            "entries_count": 0,
            "languages": set(),
            "has_summary": False,
            "has_content": False,
            "extensions": set(),
            "request_time": request_time,
            "updated_recently": False,
            "updated_date": None,
            "newest_entry_date": None,
        }

    def _handle_bozo(self, parsed_data: Any) -> None:
        err_name = (
            type(parsed_data.bozo_exception).__name__
            if parsed_data.bozo_exception
            else "BozoError"
        )
        self.stats.error_types[err_name] = self.stats.error_types.get(err_name, 0) + 1

    def _handle_unparsable(self, feed_info: Dict[str, Any], parsed_data: Any) -> None:
        feed_info["error"] = str(parsed_data.bozo_exception)
        err_type = type(parsed_data.bozo_exception).__name__
        self.stats.error_types[err_type] = self.stats.error_types.get(err_type, 0) + 1

    def _handle_process_error(
        self, feed_info: Dict[str, Any], url: str, exc: Exception
    ) -> None:
        logger.error("Error processing feed at %s", url)
        logger.error(traceback.format_exc())
        feed_info["error"] = str(exc)
        err_type = type(exc).__name__
        self.stats.error_types[err_type] = self.stats.error_types.get(err_type, 0) + 1

    def _analyze_parsed_feed(
        self,
        feed_info: Dict[str, Any],
        parsed_data: Any,
        content: bytes,
        request_time: datetime,
    ) -> None:
        feed_info["valid"] = True
        feed_info["format"] = getattr(
            parsed_data, "version", None
        ) or self._guess_format(content)
        feed_info["entries_count"] = len(parsed_data.entries)

        # Language from feed
        if parsed_data.feed.get("language"):
            feed_info["languages"].add(parsed_data.feed.get("language"))

        # Last updated
        updated_parsed = parsed_data.feed.get("updated_parsed") or parsed_data.feed.get(
            "published_parsed"
        )
        if updated_parsed:
            updated_dt = datetime(
                updated_parsed[0],
                updated_parsed[1],
                updated_parsed[2],
                updated_parsed[3],
                updated_parsed[4],
                updated_parsed[5],
                tzinfo=timezone.utc,
            )
            delta = request_time - updated_dt
            if timedelta(0) <= delta < timedelta(days=7):
                feed_info["updated_recently"] = True

        # Entry analysis
        self._analyze_entries(feed_info, parsed_data, request_time)

        feed_info["updated_date"] = parsed_data.get("feed", {}).get(
            "updated_parsed"
        ) or parsed_data.get("feed", {}).get("published_parsed")

    def _analyze_entries(
        self, feed_info: Dict[str, Any], parsed_data: Any, request_time: datetime
    ) -> None:
        content_lengths = []
        for entry in parsed_data.entries:
            # Language
            lang = entry.get("language") or parsed_data.feed.get("language")
            if lang:
                feed_info["languages"].add(lang)

            # Summary / Content
            if entry.get("summary"):
                feed_info["has_summary"] = True
            if entry.get("content"):
                feed_info["has_content"] = True
                for content_obj in entry.content:
                    if content_obj.value:
                        content_lengths.append(len(content_obj.value))

            # Recency of entries
            entry_updated = entry.get("updated_parsed") or entry.get("published_parsed")
            if entry_updated:
                # Track newest entry
                if (
                    not feed_info["newest_entry_date"]
                    or entry_updated > feed_info["newest_entry_date"]
                ):
                    feed_info["newest_entry_date"] = entry_updated

            # Extensions
            self._analyze_extensions(feed_info, entry)

        feed_info["content_lengths"] = content_lengths

    def _analyze_extensions(self, feed_info: Dict[str, Any], entry: Any) -> None:
        standard_keys = {
            "title",
            "link",
            "summary",
            "content",
            "published",
            "updated",
            "id",
            "author",
            "tags",
            "links",
            "title_detail",
            "summary_detail",
            "published_parsed",
            "updated_parsed",
        }
        for key in entry.keys():
            if key not in standard_keys:
                feed_info["extensions"].add(key)
