import hashlib
import logging
import math
import pickle
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, cast
from urllib.parse import urljoin

import dateutil.parser
import feedparser
import lxml.html
from lxml import etree

try:
    from .utils import get_domain, get_tranco_list, normalize_url
except (ImportError, ValueError):
    try:
        from utils import get_domain, get_tranco_list, normalize_url  # type: ignore
    except ImportError:
        from cc_feeds.utils import (  # type: ignore
            get_domain,
            get_tranco_list,
            normalize_url,
        )

logger = logging.getLogger(__name__)


class Stats:
    def __init__(self) -> None:
        self.pages_seen: int = 0
        self.sites_seen: Set[str] = set()
        self.sites_seen_count: int = 0
        self.autodiscovery_links: Dict[str, List[str]] = {}
        self.feed_results: Dict[str, Dict[str, Any]] = {}
        self.content_type_counts: Dict[str, int] = {}
        self.error_types: Dict[str, int] = {}
        self.top_n: Optional[int] = None
        self.max_crawl_time_str: Optional[str] = None
        self.feeds_sniffed: int = 0
        self.pages_processed: int = 0
        self.total_entries: int = 0
        self.content_length_counts: Dict[int, int] = {}  # Binned content lengths
        self.discovery_domain_counts: Dict[str, int] = {}  # feed_url -> total domains found on

        # Discovery relation tracking
        self.discovery_rel_alternate: int = 0
        self.discovery_rel_feed: int = 0
        self.discovery_rel_both_page: int = 0
        self.discovery_multi_rel_url: int = 0
        self.discovery_pages_count: int = 0
        self.multi_feed_pages: Dict[str, List[str]] = {}  # page_url -> [feed_urls]

        # HyperLogLog for unique sites (p=12 gives ~1.6% error with 4KB state)
        self.hll_p = 12
        self.hll_m = 1 << self.hll_p
        self.hll_registers = [0] * self.hll_m

        # Detailed language tracking
        self.lang_src_http: int = 0
        self.lang_src_feed: int = 0
        self.lang_src_entry: int = 0
        self.lang_mismatches: int = 0
        self.lang_multiple_in_feed: int = 0

    def merge(self, other: "Stats") -> None:
        """Merge another Stats object into this one."""
        if other.max_crawl_time_str:
            if (
                not self.max_crawl_time_str
                or other.max_crawl_time_str > self.max_crawl_time_str
            ):
                self.max_crawl_time_str = other.max_crawl_time_str
        self.pages_seen += other.pages_seen
        self.feeds_sniffed += other.feeds_sniffed
        self.pages_processed += other.pages_processed
        self.total_entries += other.total_entries
        
        # Merge content length histogram
        for length, count in getattr(other, "content_length_counts", {}).items():
            self.content_length_counts[length] = self.content_length_counts.get(length, 0) + count

        self.discovery_rel_alternate += other.discovery_rel_alternate
        self.discovery_rel_feed += other.discovery_rel_feed
        self.discovery_rel_both_page += other.discovery_rel_both_page
        self.discovery_multi_rel_url += other.discovery_multi_rel_url
        self.discovery_pages_count += getattr(other, "discovery_pages_count", 0)

        for page_url, feed_urls in getattr(other, "multi_feed_pages", {}).items():
            if page_url not in self.multi_feed_pages:
                self.multi_feed_pages[page_url] = []
            # Merge feed URL lists for the same page
            existing = set(self.multi_feed_pages[page_url])
            for f in feed_urls:
                if f not in existing:
                    self.multi_feed_pages[page_url].append(f)
        self.lang_src_http += other.lang_src_http
        self.lang_src_feed += other.lang_src_feed
        self.lang_src_entry += other.lang_src_entry
        self.lang_mismatches += other.lang_mismatches
        self.lang_multiple_in_feed += other.lang_multiple_in_feed
        self.sites_seen.update(other.sites_seen)
        self.sites_seen_count += getattr(other, "sites_seen_count", 0)

        for feed_url, domains in other.autodiscovery_links.items():
            if feed_url not in self.autodiscovery_links:
                self.autodiscovery_links[feed_url] = []
            # Merge domain lists (as samples)
            existing = set(self.autodiscovery_links[feed_url])
            for d in domains:
                if d not in existing and len(existing) < 100:
                    self.autodiscovery_links[feed_url].append(d)
                    existing.add(d)

        # Merge domain counts
        for feed_url, count in getattr(other, "discovery_domain_counts", {}).items():
            self.discovery_domain_counts[feed_url] = self.discovery_domain_counts.get(feed_url, 0) + count

        for ct, count in other.content_type_counts.items():
            self.content_type_counts[ct] = self.content_type_counts.get(ct, 0) + count

        self.feed_results.update(other.feed_results)

        for err_type, count in other.error_types.items():
            self.error_types[err_type] = self.error_types.get(err_type, 0) + count

        # Merge HLL registers
        other_hll = getattr(other, "hll_registers", None)
        if other_hll:
            for i in range(self.hll_m):
                self.hll_registers[i] = max(self.hll_registers[i], other_hll[i])

        other_top_n = getattr(other, "top_n", None)
        if other_top_n is not None:
            if self.top_n is None or other_top_n > self.top_n:
                self.top_n = other_top_n

    def save(self, path: str) -> None:
        with open(path, "wb") as f_out:
            pickle.dump(self, f_out)

    @classmethod
    def load(cls, path: str) -> "Stats":
        with open(path, "rb") as f_in:
            return cast(Stats, pickle.load(f_in))

    def add_site(self, domain: str) -> None:
        """Add a site to the HLL counter and (optionally) the set."""
        if not domain:
            return
        self.sites_seen.add(domain)  # Still keep for small runs/samples

        # Deterministic hash for HLL
        h = int(hashlib.md5(domain.encode("utf-8")).hexdigest()[:16], 16)
        idx = h & (self.hll_m - 1)
        # rho(w) is the number of leading zeros + 1 in the remaining 64-p bits
        # If hash is 64 bits and p=12, w has 52 bits.
        w_bits = 64 - self.hll_p
        rho = (w_bits - w.bit_length() + 1) if w > 0 else (w_bits + 1)
        self.hll_registers[idx] = max(self.hll_registers[idx], rho)

    def get_unique_sites_estimate(self) -> int:
        """Return the HLL estimate of unique sites."""
        # Alpha_m for p=12 is 0.7213 / (1 + 1.079 / m)
        alpha = 0.7213 / (1 + 1.079 / self.hll_m)
        Z = sum(2.0**-r for r in self.hll_registers)
        E = alpha * (self.hll_m**2) / Z

        # Small range correction
        if E <= 2.5 * self.hll_m:
            V = self.hll_registers.count(0)
            if V > 0:
                E = self.hll_m * math.log(self.hll_m / V)
        return int(E)


class WarcProcessor:
    def __init__(self, top_n: Optional[int] = None) -> None:
        self.top_n_domains: Optional[Set[str]] = (
            get_tranco_list(top_n) if top_n else None
        )
        self.stats: Stats = Stats()
        self.stats.top_n = top_n

    def is_in_scope(self, domain: str) -> bool:
        if not self.top_n_domains:
            return True
        # Check domain and subdomains if necessary, but Tranco is usually just domains
        return domain in self.top_n_domains or (
            domain.count(".") > 0 and domain.split(".", 1)[-1] in self.top_n_domains
        )

    def process_record(self, record: Any) -> None:
        if record.headers.get("WARC-Type") != "response":
            return

        url = record.headers.get("WARC-Target-URI")
        if not url:
            return

        # Fast domain extraction (used for both scope and site tracking)
        domain = get_domain(url)
        if not self.is_in_scope(domain):
            return

        # Track latest crawl time using string comparison to avoid parsing every date
        request_time_str = record.headers.get("WARC-Date")
        if request_time_str:
            if (
                not self.stats.max_crawl_time_str
                or request_time_str > self.stats.max_crawl_time_str
            ):
                self.stats.max_crawl_time_str = request_time_str

        # Update general stats
        self.stats.pages_seen += 1
        self.stats.pages_processed += 1

        # Fast domain extraction and site tracking
        if domain:
            self.stats.add_site(domain)

        # 1. Technical summary for relevant records
        h = record.http_headers
        if not h:
            return

        content_type_header = h.get("Content-Type", "")
        content_type = content_type_header.split(";")[0].strip().lower()
        if content_type:
            self.stats.content_type_counts[content_type] = (
                self.stats.content_type_counts.get(content_type, 0) + 1
            )

        # 2. Check for HTML/Feeds
        if "text/html" in content_type:
            # User requested 12KB for every page (more than enough for most <head> sections)
            content = record.reader.read(12288)
            self._process_html(record, url, content)
            return

        # 3. Check if this record itself is a feed
        status_code: int = getattr(h, "status_code", 200)
        ct_main = content_type.split(";")[0].strip().lower()
        is_feed = (
            "rss" in ct_main
            or "atom" in ct_main
            or "feed+json" in ct_main
            or ct_main in ("application/xml", "text/xml")
        )
        if is_feed and status_code == 200:
            import sys

            sys.stderr.write(f"DEBUG: Processing feed record: {url}\n")
            sys.stderr.flush()
            # IMPORTANT: Normalize URL so it matches autodiscovery links later
            normalized_url = normalize_url(url)
            self._process_feed(record, normalized_url, status_code)
        elif "text/plain" in content_type or "application/octet-stream" in content_type:
            # Sniff the first few bytes for feed signatures (only if reader supports peek)
            try:
                if (
                    hasattr(record.reader, "peek")
                    and self._guess_format(record.reader.peek(1024)) != "unknown"
                ):
                    self.stats.feeds_sniffed += 1
                    self._process_feed(record, url, status_code)
            except (AttributeError, Exception):
                pass

    def _process_html(self, record: Any, url: str, content: bytes) -> None:
        if not content:
            return

        try:

            # FAST PRE-FILTER: Avoid expensive LXML parsing for pages without feed links
            if (
                b"rss+xml" not in content
                and b"atom+xml" not in content
                and b"feed+json" not in content
            ):
                return

            doc = lxml.html.fromstring(content)
            # Find both alternate and feed relations
            links = doc.xpath('//link[@rel="alternate" or @rel="feed"]')
            if not isinstance(links, list):
                return

            found_rels: Set[str] = set()  # relations found on this page
            page_discoveries: Dict[str, Set[str]] = (
                {}
            )  # feed_url -> set of rels on this page

            for link in links:
                if not isinstance(link, etree._Element):
                    continue

                rel = str(link.get("rel", "")).lower()
                link_type = str(link.get("type", "")).lower()

                # Only interested in feed types
                if (
                    "rss+xml" not in link_type
                    and "atom+xml" not in link_type
                    and "feed+json" not in link_type
                ):
                    continue

                href = link.get("href")
                if not href:
                    continue

                feed_url = normalize_url(urljoin(url, str(href)))
                found_rels.add(rel)

                if feed_url not in page_discoveries:
                    page_discoveries[feed_url] = set()
                page_discoveries[feed_url].add(rel)

                # Record the discovery (track domains as samples to save space)
                domain = get_domain(url)
                if feed_url not in self.stats.autodiscovery_links:
                    self.stats.autodiscovery_links[feed_url] = []
                    self.stats.discovery_domain_counts[feed_url] = 0
                
                self.stats.discovery_domain_counts[feed_url] += 1
                if (
                    domain not in self.stats.autodiscovery_links[feed_url]
                    and len(self.stats.autodiscovery_links[feed_url]) < 10
                ):
                    self.stats.autodiscovery_links[feed_url].append(domain)

            # Update relation stats
            if found_rels:
                self.stats.discovery_pages_count += 1

            if "alternate" in found_rels:
                self.stats.discovery_rel_alternate += 1
            if "feed" in found_rels:
                self.stats.discovery_rel_feed += 1
            if "alternate" in found_rels and "feed" in found_rels:
                self.stats.discovery_rel_both_page += 1

            if len(page_discoveries) > 1:
                # Store the full feed URL list for pages with multiple feeds to detect duplicates later
                # We limit this to a reasonable number of pages to avoid memory bloat in huge runs
                if len(self.stats.multi_feed_pages) < 10000:
                    self.stats.multi_feed_pages[url] = list(page_discoveries.keys())

        except Exception:
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

        # Extract technical details
        content_type_header = record.http_headers.get("Content-Type", "")
        content_type = content_type_header.split(";")[0].strip().lower()
        charset = ""
        if ";" in content_type_header:
            parts = content_type_header.split(";")
            for part in parts[1:]:
                if "charset=" in part.lower():
                    charset = part.lower().split("charset=")[1].strip().strip('"')

        feed_info = self._init_feed_info(
            status_code, request_time, url, content_type, charset
        )

        if not 200 <= status_code < 400:
            self.stats.feed_results[url] = feed_info
            return

        try:
            # Read the entire body for parsing
            content = record.reader.read()
            if not content:
                return

            parsed_data = feedparser.parse(content)

            if parsed_data.bozo:
                self._handle_bozo(parsed_data)

            # Track language from HTTP headers
            lang_header = record.http_headers.get("Content-Language")
            if lang_header:
                http_lang = lang_header.split(",")[0].strip().lower()
                feed_info["lang_http"] = http_lang
                feed_info["languages"].add(http_lang)
                self.stats.lang_src_http += 1

            if not parsed_data.bozo or parsed_data.entries:
                self._analyze_parsed_feed(feed_info, parsed_data, content, request_time)
            else:
                self._handle_unparsable(feed_info, parsed_data)

        except Exception as exc:  # pylint: disable=broad-except
            self._handle_process_error(feed_info, url, exc)

        self.stats.feed_results[url] = feed_info

    def _init_feed_info(
        self,
        status_code: int,
        request_time: datetime,
        url: str,
        content_type: str,
        charset: str,
    ) -> Dict[str, Any]:
        return {
            "url": url,
            "status": status_code,
            "content_type": content_type,
            "charset": charset,
            "valid": False,
            "format": None,
            "entries_count": 0,
            "lang_http": None,
            "lang_feed": None,
            "lang_entries": set(),
            "languages": set(),
            "has_summary": False,
            "has_content": False,
            "extensions": set(),
            "request_time": request_time,
            "updated_recently": False,
            "updated_date": None,
            "newest_entry_date": None,
            "title": None,
            "link": None,
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
        self.stats.total_entries += len(parsed_data.entries)

        # Title and Link
        title = parsed_data.feed.get("title")
        if title:
            feed_info["title"] = title.strip()
        link = parsed_data.feed.get("link")
        if link:
            from utils import normalize_url

            feed_info["link"] = normalize_url(link)

        # Language from feed
        feed_lang = parsed_data.feed.get("language")
        if feed_lang:
            feed_lang = feed_lang.lower()
            feed_info["lang_feed"] = feed_lang
            feed_info["languages"].add(feed_lang)
            self.stats.lang_src_feed += 1

            # Check mismatch with HTTP
            if feed_info["lang_http"] and feed_info["lang_http"] != feed_lang:
                self.stats.lang_mismatches += 1

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
        entry_langs = set()
        for entry in parsed_data.entries:
            # Language
            lang = entry.get("language")
            if lang:
                lang = lang.lower()
                entry_langs.add(lang)
                feed_info["languages"].add(lang)
                self.stats.lang_src_entry += 1

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
        for length in content_lengths:
            # Bin to nearest 100 bytes to reduce histogram size
            binned = (length // 100) * 100
            self.stats.content_length_counts[binned] = self.stats.content_length_counts.get(binned, 0) + 1

        if entry_langs:
            feed_info["lang_entries"].update(entry_langs)
            if len(entry_langs) > 1:
                self.stats.lang_multiple_in_feed += 1
            # Also check if entry languages differ from feed/http
            base_lang = feed_info["lang_feed"] or feed_info["lang_http"]
            if base_lang and any(l != base_lang for l in entry_langs):
                if (
                    len(entry_langs) == 1
                ):  # If only one entry lang, but different from base
                    self.stats.lang_mismatches += 1

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
