from typing import Any, Optional

from fastwarc.warc import WarcRecordType

from cc_feeds.analysis.feed_analysis import FeedAnalyzer
from cc_feeds.analysis.formats import guess_feed_format
from cc_feeds.analysis.html_discovery import HtmlDiscovery
from cc_feeds.analysis.scope import DomainScope
from cc_feeds.analysis.stats import Stats
from cc_feeds.url import get_domain, normalize_url


class WarcProcessor:
    def __init__(self, top_n: Optional[int] = None) -> None:
        self.stats: Stats = Stats()
        self.stats.top_n = top_n
        self.scope = DomainScope(top_n)
        self.html_discovery = HtmlDiscovery(self.stats)
        self.feed_analyzer = FeedAnalyzer(self.stats)

    def is_in_scope(self, domain: str) -> bool:
        return self.scope.includes(domain)

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
        http_headers = record.http_headers
        if not http_headers:
            return

        # 5. CONTENT-TYPE RE-VERIFICATION (HTTP-level)
        ct_header = http_headers.get("Content-Type", "")

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
                self._process_html(url, content)
            except Exception:
                pass
            return

        # 8. Feed processing
        status_code: int = http_headers.status_code
        if status_code == 200:
            normalized_url = normalize_url(url)
            self._process_feed(record, normalized_url, status_code, request_time_str)
        elif "text/plain" in content_type or "application/octet-stream" in content_type:
            # Sniff the first few bytes for feed signatures (only if reader supports peek)
            try:
                if (
                    hasattr(record.reader, "peek")
                    and guess_feed_format(record.reader.peek(1024)) != "unknown"
                ):
                    self.stats.feeds_sniffed += 1
                    self._process_feed(record, url, status_code, request_time_str)
            except (AttributeError, Exception):
                pass

    def _process_html(self, url: str, content: bytes) -> None:
        self.html_discovery.process(url, content)

    def _guess_format(self, content: bytes) -> str:
        return guess_feed_format(content)

    def _process_feed(
        self,
        record: Any,
        url: str,
        status_code: int,
        request_time_str: Optional[str] = None,
    ) -> None:
        self.feed_analyzer.process(record, url, status_code, request_time_str)
