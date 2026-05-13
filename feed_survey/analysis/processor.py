from typing import Any, Optional

from fastwarc.warc import WarcRecordType  # pylint: disable=no-name-in-module

from feed_survey.analysis.content_types import (
    feed_content_type,
    interesting_http_content_type,
    interesting_warc_content_type,
    normalized_content_type,
    sniffable_content_type,
)
from feed_survey.analysis.feed_analysis import FeedAnalyzer
from feed_survey.analysis.formats import guess_feed_format
from feed_survey.analysis.html_discovery import HtmlDiscovery
from feed_survey.analysis.scope import SiteScope
from feed_survey.analysis.stats import Stats
from feed_survey.url import get_site, normalize_url


class WarcProcessor:
    def __init__(
        self, top_n: Optional[int] = None, tranco_include_subdomains: bool = True
    ) -> None:
        self.stats: Stats = Stats()
        self.stats.top_n = top_n
        self.stats.tranco_include_subdomains = tranco_include_subdomains
        self.scope = SiteScope(top_n, include_subdomains=tranco_include_subdomains)
        self.html_discovery = HtmlDiscovery(self.stats)
        self.feed_analyzer = FeedAnalyzer(self.stats)

    def is_in_scope(self, site: str) -> bool:
        return self.scope.includes(site)

    def process_record(self, record: Any) -> None:
        if record.record_type != WarcRecordType.response:
            return

        url = record.headers.get("WARC-Target-URI")
        site = get_site(url or "")
        if not url or not self.is_in_scope(site):
            return

        self.stats.responses_processed += 1
        if not interesting_warc_content_type(record):
            return

        record.parse_http()
        http_headers = record.http_headers
        if not http_headers:
            return

        ct_header = http_headers.get("Content-Type", "")
        if not interesting_http_content_type(ct_header):
            return

        content_type = normalized_content_type(ct_header)
        request_time_str = record.headers.get("WARC-Date")
        self._record_page_metadata(site, content_type, request_time_str)

        if "text/html" in content_type:
            self._process_html_snippet(record, url)
            return

        status_code: int = http_headers.status_code
        if status_code == 200:
            if feed_content_type(content_type):
                normalized_url = normalize_url(url)
                self._process_feed(
                    record,
                    normalized_url,
                    status_code,
                    request_time_str,
                    candidate_source="feed_media_type",
                )
            elif sniffable_content_type(content_type):
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
            content = record.reader.read(10 * 1024 * 1024)
            if not content or guess_feed_format(content[:1024]) == "unknown":
                return
            self.stats.feeds_sniffed += 1
            self.feed_analyzer.process_content(
                record,
                normalize_url(url),
                status_code=status_code,
                content=content,
                request_time_str=request_time_str,
                candidate_source="sniffed",
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            pass

    def _record_page_metadata(
        self, site: str, content_type: str, request_time_str: Optional[str]
    ) -> None:
        if content_type:
            self.stats.content_type_counts[content_type] = (
                self.stats.content_type_counts.get(content_type, 0) + 1
            )

        self.stats.pages_seen += 1
        self.stats.pages_processed += 1
        if site:
            self.stats.add_site(site)

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
        *,
        candidate_source: str = "feed_media_type",
    ) -> None:
        self.feed_analyzer.process(
            record,
            url,
            status_code,
            request_time_str,
            candidate_source=candidate_source,
        )
