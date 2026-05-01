import hashlib
import logging
import math
import pickle
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, cast
from urllib.parse import urljoin

import dateutil.parser
import lxml.html
from fastwarc.warc import WarcRecordType
from lxml import etree

sys.stderr.write("DEBUG: processor.py module loading...\n")
sys.stderr.flush()

try:
    from .fast_parser import FastFeedParser
    from .quality import score_feed
    from .utils import get_domain, get_tranco_list, normalize_url
except (ImportError, ValueError):
    try:
        from fast_parser import FastFeedParser  # type: ignore
        from quality import score_feed  # type: ignore
        from utils import get_domain, get_tranco_list, normalize_url  # type: ignore
    except ImportError:
        from cc_feeds.fast_parser import FastFeedParser
        from cc_feeds.quality import score_feed
        from cc_feeds.utils import (
            get_domain,
            get_tranco_list,
            normalize_url,
        )

sys.stderr.write("DEBUG: processor.py dependencies loaded\n")
sys.stderr.flush()

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
        self.discovery_domain_counts: Dict[str, int] = (
            {}
        )  # feed_url -> total domains found on

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
            self.content_length_counts[length] = (
                self.content_length_counts.get(length, 0) + count
            )

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
            self.discovery_domain_counts[feed_url] = (
                self.discovery_domain_counts.get(feed_url, 0) + count
            )

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
        """Add a site to the HLL counter and the set."""
        if not domain:
            return
        self.sites_seen.add(domain)

        # Faster HLL hashing using CRC32 (stable and fast for non-crypto use)
        import zlib

        h = zlib.crc32(domain.encode("utf-8")) & 0xFFFFFFFF

        idx = h & (self.hll_m - 1)
        w_bits = 32 - self.hll_p
        w = h >> self.hll_p
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
        self.html_parser = lxml.html.HTMLParser(recover=True, encoding="utf-8")
        self._scope_cache: Dict[str, bool] = {}

    def is_in_scope(self, domain: str) -> bool:
        if not self.top_n_domains:
            return True
        if not domain:
            return False

        if domain in self._scope_cache:
            return self._scope_cache[domain]

        # Check domain and all parent domains (e.g., sub.example.com -> example.com)
        in_scope = False
        parts = domain.split(".")
        for i in range(len(parts)):
            if ".".join(parts[i:]) in self.top_n_domains:
                in_scope = True
                break

        # Cap cache size to avoid memory issues
        if len(self._scope_cache) < 50000:
            self._scope_cache[domain] = in_scope
        return in_scope

    def process_record(self, record: Any) -> None:
        # 1. Immediate exit for non-responses (very fast)
        if record.record_type != WarcRecordType.response:
            return

        # 2. FAST METADATA FILTER (WARC-level)
        # Common Crawl provides the identified payload type in WARC headers.
        # This allows us to skip HTTP parsing for 80% of records.
        warc_ct = record.headers.get("WARC-Identified-Payload-Type", "")
        if warc_ct and not (
            "text/html" in warc_ct
            or "xml" in warc_ct
            or "rss" in warc_ct
            or "json" in warc_ct
        ):
            return

        # 3. Target URI and Scope (Check before expensive HTTP parsing)
        # Fetch URI once to avoid multiple decodes in fastwarc
        url = record.headers.get("WARC-Target-URI")
        if not url:
            return

        domain = get_domain(url)
        if not self.is_in_scope(domain):
            return

        # 4. Lazy parse HTTP headers ONLY for potentially interesting records
        record.parse_http()
        h = record.http_headers
        if not h:
            return

        # 5. CONTENT-TYPE RE-VERIFICATION (HTTP-level)
        ct_header = h.get("Content-Type", "")

        # Fast path: check for interesting types in the raw string
        if not (
            "text/html" in ct_header
            or "xml" in ct_header
            or "rss" in ct_header
            or "json" in ct_header
        ):
            return

        # Normalize content type for stats
        ct_lower = ct_header.lower()
        content_type = ct_lower.split(";")[0].strip()
        if content_type:
            self.stats.content_type_counts[content_type] = (
                self.stats.content_type_counts.get(content_type, 0) + 1
            )

        # 6. General stats and date (only for in-scope interesting records)
        self.stats.pages_seen += 1

        # Capture request time once from WARC headers to avoid redundant decodes
        request_time_str = record.headers.get("WARC-Date")
        self.stats.pages_processed += 1
        if domain:
            self.stats.add_site(domain)

        if request_time_str:
            if (
                not self.stats.max_crawl_time_str
                or request_time_str > self.stats.max_crawl_time_str
            ):
                self.stats.max_crawl_time_str = request_time_str

        # 7. Process based on type
        if "text/html" in content_type:
            # ONLY read a small snippet to find feed links
            # NEVER use record.body as it triggers a full download of the entire record
            try:
                content = record.reader.read(12288)
                self._process_html(record, url, content)
            except Exception:
                pass
            return

        # 7. Feed processing
        status_code: int = h.status_code
        if status_code == 200:
            normalized_url = normalize_url(url)
            self._process_feed(record, normalized_url, status_code, request_time_str)
        elif "text/plain" in content_type or "application/octet-stream" in content_type:
            # Sniff the first few bytes for feed signatures (only if reader supports peek)
            try:
                if (
                    hasattr(record.reader, "peek")
                    and self._guess_format(record.reader.peek(1024)) != "unknown"
                ):
                    self.stats.feeds_sniffed += 1
                    self._process_feed(record, url, status_code, request_time_str)
            except (AttributeError, Exception):
                pass

    # Pre-compiled regex for fast link detection
    _LINK_RE = re.compile(
        b"<link\\s+[^>]*rel=[\"'](?:alternate|feed)[\"'][^>]*>", re.IGNORECASE
    )
    _FEED_TYPE_RE = re.compile(
        b"type=[\"']application/(?:rss\\+xml|atom\\+xml|feed\\+json)[\"']",
        re.IGNORECASE,
    )

    def _process_html(self, record: Any, url: str, content: bytes) -> None:
        if not content:
            return

        try:
            # FAST REGEX PRE-FILTER: Avoid LXML for pages without feed links
            # We look for <link rel="alternate" ...> or <link rel="feed" ...>
            # AND a feed-related content type
            if not self._LINK_RE.search(content) or not self._FEED_TYPE_RE.search(
                content
            ):
                return

            # Faster snippet parsing using the shared HTMLParser
            doc = lxml.html.fromstring(content, parser=self.html_parser)
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

    def _process_feed(
        self,
        record: Any,
        url: str,
        status_code: int,
        request_time_str: Optional[str] = None,
    ) -> None:
        if not request_time_str:
            request_time_str = record.headers.get("WARC-Date")

        if request_time_str:
            # Fast path for WARC-Date which is usually YYYY-MM-DDTHH:MM:SSZ
            try:
                if len(request_time_str) == 20 and request_time_str.endswith("Z"):
                    request_time = datetime.strptime(
                        request_time_str, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                else:
                    request_time = dateutil.parser.parse(request_time_str)
                    if request_time.tzinfo is None:
                        request_time = request_time.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                request_time = datetime.now(timezone.utc)
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
            # Cap at 10 MB — no legitimate feed is larger, and oversized
            # bodies (e.g. content:encoded with huge embedded HTML) can make
            # lxml's iterparse very slow.
            content = record.reader.read(10 * 1024 * 1024)

            if not content:
                return

            # Use FastFeedParser for high-performance parsing
            parsed_data = FastFeedParser.parse(content)

            if not parsed_data.get("valid"):
                err = parsed_data.get("error", "parse failed")
                err_type = (
                    type(err).__name__ if not isinstance(err, str) else "ParseError"
                )
                self.stats.error_types[err_type] = (
                    self.stats.error_types.get(err_type, 0) + 1
                )
                return

            # Track language from HTTP headers
            lang_header = record.http_headers.get("Content-Language")
            if lang_header:
                http_lang = lang_header.split(",")[0].strip().lower()
                feed_info["lang_http"] = http_lang
                feed_info["languages"].add(http_lang)
                self.stats.lang_src_http += 1

            self._analyze_parsed_feed(feed_info, parsed_data, content, request_time)

        except Exception as exc:  # pylint: disable=broad-except
            self._handle_process_error(feed_info, url, exc)

        feed_info["quality"] = score_feed(feed_info, request_time)
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
            "oldest_entry_date": None,
            "all_languages": set(),
            "content_type_profile": "unknown",
            "title": None,
            "link": None,
        }

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

        feed_data = parsed_data.get("feed", {})
        feed_info["format"] = parsed_data.get("version") or self._guess_format(content)
        entries_count = parsed_data.get("entries_count", 0)
        feed_info["extensions"] = parsed_data.get("extensions", set())
        feed_info["has_content"] = parsed_data.get("has_content", False)
        feed_info["has_summary"] = parsed_data.get("has_summary", False)
        feed_info["content_type_profile"] = parsed_data.get(
            "content_type_profile", "unknown"
        )
        feed_info["all_languages"] = parsed_data.get("all_languages", set())

        feed_info["entries_count"] = entries_count
        self.stats.total_entries += entries_count

        # Title and Link
        title = feed_data.get("title")
        if title:
            feed_info["title"] = title.strip()
        link = feed_data.get("link")
        if link:
            feed_info["link"] = normalize_url(link)

        # Language from feed element (xml:lang or <language> child)
        feed_lang = feed_data.get("language")
        if not feed_lang:
            # Fall back to first all_languages value if set (xml:lang on root)
            all_langs = feed_info.get("all_languages", set())
            if all_langs:
                feed_lang = next(iter(all_langs))
        if feed_lang:
            feed_lang = feed_lang.lower()
            feed_info["lang_feed"] = feed_lang
            feed_info["languages"].add(feed_lang)
            self.stats.lang_src_feed += 1

            # Check mismatch with HTTP Content-Language
            if feed_info["lang_http"] and feed_info["lang_http"] != feed_lang:
                self.stats.lang_mismatches += 1

        # Last updated — updated_parsed is already a [y,m,d,H,M,S,...] list
        updated_parsed = feed_data.get("updated_parsed")
        if updated_parsed:
            try:
                updated_dt = datetime(
                    updated_parsed[0],
                    updated_parsed[1],
                    updated_parsed[2],
                    updated_parsed[3],
                    updated_parsed[4],
                    updated_parsed[5],
                    tzinfo=timezone.utc,
                )
                if timedelta(0) <= request_time - updated_dt < timedelta(days=7):
                    feed_info["updated_recently"] = True
            except (ValueError, TypeError, IndexError):
                pass

        feed_info["updated_date"] = updated_parsed

        # Entry analysis
        self._analyze_entries(feed_info, parsed_data, request_time)

    def _analyze_entries(
        self, feed_info: Dict[str, Any], parsed_data: Any, request_time: datetime
    ) -> None:
        """Analyze entry dates and content structure."""
        newest_date = parsed_data.get("newest_entry_date")
        oldest_date = parsed_data.get("oldest_entry_date")
        content_lengths = parsed_data.get("content_lengths", [])
        entry_langs = parsed_data.get("entry_languages", set())
        all_langs = parsed_data.get("all_languages", set())

        if entry_langs:
            self.stats.lang_src_entry += len(entry_langs)
            feed_info["languages"].update(entry_langs)
            feed_info["lang_entries"].update(entry_langs)

        # Count feeds with more than one language anywhere in the document
        if len(all_langs) > 1:
            self.stats.lang_multiple_in_feed += 1

        # Check if entry languages conflict with feed/http language
        if entry_langs:
            base_lang = feed_info["lang_feed"] or feed_info["lang_http"]
            if base_lang and any(l != base_lang for l in entry_langs):
                if len(entry_langs) == 1:
                    self.stats.lang_mismatches += 1

        if newest_date:
            try:
                entry_dt = datetime(
                    newest_date[0],
                    newest_date[1],
                    newest_date[2],
                    newest_date[3],
                    newest_date[4],
                    newest_date[5],
                    tzinfo=timezone.utc,
                )
                delta = request_time - entry_dt
                if timedelta(0) <= delta < timedelta(days=7):
                    feed_info["entry_recently"] = True
            except Exception:
                pass

        feed_info["newest_entry_date"] = newest_date
        feed_info["oldest_entry_date"] = oldest_date
        feed_info["content_lengths"] = content_lengths
        for length in content_lengths:
            # Bin to nearest 100 bytes to reduce histogram size
            binned = (length // 100) * 100
            self.stats.content_length_counts[binned] = (
                self.stats.content_length_counts.get(binned, 0) + 1
            )
