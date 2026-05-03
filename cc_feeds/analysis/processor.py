from typing import Any, Optional

from fastwarc.warc import WarcRecordType  # pylint: disable=no-name-in-module

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
        if record.record_type != WarcRecordType.response:
            return
        if not _interesting_warc_content_type(record):
            return

        url = record.headers.get("WARC-Target-URI")
        domain = get_domain(url or "")
        if not url or not self.is_in_scope(domain):
            return

        record.parse_http()
        http_headers = record.http_headers
        if not http_headers:
            return

        ct_header = http_headers.get("Content-Type", "")
        if not _interesting_http_content_type(ct_header):
            return

        content_type = _normalized_content_type(ct_header)
        request_time_str = record.headers.get("WARC-Date")
        self._record_page_metadata(domain, content_type, request_time_str)

        if "text/html" in content_type:
            self._process_html_snippet(record, url)
            return

        status_code: int = http_headers.status_code
        if status_code == 200:
            if _feed_content_type(content_type):
                normalized_url = normalize_url(url)
                self._process_feed(record, normalized_url, status_code, request_time_str)
            elif _sniffable_content_type(content_type):
                self._process_sniffed_feed(record, url, status_code, request_time_str)

    def _process_html(self, url: str, content: bytes) -> None:
        self.html_discovery.process(url, content)

    def _process_html_snippet(self, record: Any, url: str) -> None:
        try:
            content = record.reader.read(12288)
            self._process_html(url, content)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    def _process_sniffed_feed(
        self,
        record: Any,
        url: str,
        status_code: int,
        request_time_str: Optional[str],
    ) -> None:
        try:
            if (
                hasattr(record.reader, "peek")
                and guess_feed_format(record.reader.peek(1024)) != "unknown"
            ):
                self.stats.feeds_sniffed += 1
                self._process_feed(
                    record, normalize_url(url), status_code, request_time_str
                )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            pass

    def _record_page_metadata(
        self, domain: str, content_type: str, request_time_str: Optional[str]
    ) -> None:
        if content_type:
            self.stats.content_type_counts[content_type] = (
                self.stats.content_type_counts.get(content_type, 0) + 1
            )

        self.stats.pages_seen += 1
        self.stats.pages_processed += 1
        if domain:
            self.stats.add_site(domain)

        if request_time_str and (
            not self.stats.max_crawl_time_str
            or request_time_str > self.stats.max_crawl_time_str
        ):
            self.stats.max_crawl_time_str = request_time_str

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


def _interesting_warc_content_type(record: Any) -> bool:
    warc_ct = record.headers.get("WARC-Identified-Payload-Type", "")
    return not warc_ct or _interesting_content_type(warc_ct)


def _interesting_http_content_type(content_type_header: str) -> bool:
    return _interesting_content_type(content_type_header)


def _interesting_content_type(content_type_header: str) -> bool:
    content_type = content_type_header.lower()
    return (
        "text/html" in content_type
        or "xml" in content_type
        or "rss" in content_type
        or "text/plain" in content_type
        or "application/octet-stream" in content_type
    )


def _normalized_content_type(content_type_header: str) -> str:
    return content_type_header.lower().split(";")[0].strip()


def _feed_content_type(content_type: str) -> bool:
    return (
        content_type in {
            "application/rss+xml",
            "application/atom+xml",
            "application/xml+rss",
            "text/rss",
            "text/atom",
        }
        or content_type.endswith("+rss")
        or content_type.endswith("+atom")
    )


def _sniffable_content_type(content_type: str) -> bool:
    return (
        "xml" in content_type
        or "text/plain" in content_type
        or "application/octet-stream" in content_type
    )
