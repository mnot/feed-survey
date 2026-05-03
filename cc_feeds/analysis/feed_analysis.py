import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import dateutil.parser

from cc_feeds.analysis.fast_parser import FastFeedParser
from cc_feeds.analysis.formats import guess_feed_format
from cc_feeds.analysis.stats import Stats
from cc_feeds.url import normalize_url

logger = logging.getLogger(__name__)


class FeedAnalyzer:
    def __init__(self, stats: Stats) -> None:
        self.stats = stats

    def process(
        self,
        record: Any,
        url: str,
        status_code: int,
        request_time_str: Optional[str] = None,
    ) -> None:
        request_time = _parse_request_time(
            request_time_str or record.headers.get("WARC-Date")
        )
        url = normalize_url(url)
        content_type, charset = _content_type_parts(
            record.http_headers.get("Content-Type", "")
        )

        feed_info = _init_feed_info(
            status_code, request_time, url, content_type, charset
        )
        if not 200 <= status_code < 400:
            self.stats.feed_results[url] = feed_info
            return

        try:
            content = record.reader.read(10 * 1024 * 1024)
            if not content:
                feed_info["error"] = "Empty response"
                self._record_parse_error(feed_info)
                self.stats.feed_results[url] = feed_info
                return

            parsed_data = FastFeedParser.parse(content)
            if not parsed_data.get("valid"):
                self._record_parse_error(parsed_data)
                feed_info["error"] = parsed_data.get("error", "parse failed")
                self.stats.feed_results[url] = feed_info
                return

            self._record_http_language(record, feed_info)
            self._analyze_parsed_feed(feed_info, parsed_data, content, request_time)
        except (OSError, RuntimeError, SyntaxError, TypeError, ValueError) as exc:
            self._handle_process_error(feed_info, url, exc)

        self.stats.feed_results[url] = feed_info

    def _record_parse_error(self, parsed_data: Dict[str, Any]) -> None:
        err = parsed_data.get("error", "parse failed")
        err_type = type(err).__name__ if not isinstance(err, str) else "ParseError"
        self.stats.error_types[err_type] = self.stats.error_types.get(err_type, 0) + 1

    def _record_http_language(self, record: Any, feed_info: Dict[str, Any]) -> None:
        lang_header = record.http_headers.get("Content-Language")
        if lang_header:
            http_lang = lang_header.split(",")[0].strip().lower()
            feed_info["lang_http"] = http_lang
            feed_info["languages"].add(http_lang)
            self.stats.lang_src_http += 1

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
        feed_info["format"] = parsed_data.get("version") or guess_feed_format(content)
        entries_count = parsed_data.get("entries_count", 0)
        feed_info["extensions"] = parsed_data.get("extensions", set())
        feed_info["has_content"] = parsed_data.get("has_content", False)
        feed_info["has_summary"] = parsed_data.get("has_summary", False)
        feed_info["content_type_profile"] = parsed_data.get(
            "content_type_profile", "unknown"
        )
        feed_info["all_languages"] = parsed_data.get("all_languages", set())
        feed_info["entry_title_count"] = parsed_data.get("entry_title_count", 0)
        feed_info["repeated_entry_title_count"] = parsed_data.get(
            "repeated_entry_title_count", 0
        )
        feed_info["repeated_entry_title_ratio"] = parsed_data.get(
            "repeated_entry_title_ratio", 0.0
        )
        feed_info["default_entry_title_count"] = parsed_data.get(
            "default_entry_title_count", 0
        )

        feed_info["entries_count"] = entries_count
        self.stats.total_entries += entries_count

        title = feed_data.get("title")
        if title:
            feed_info["title"] = title.strip()
        link = feed_data.get("link")
        if link:
            feed_info["link"] = normalize_url(link)

        self._record_feed_language(feed_info, feed_data)
        self._record_feed_recency(feed_info, feed_data, request_time)
        self._analyze_entries(feed_info, parsed_data, request_time)

    def _record_feed_language(
        self, feed_info: Dict[str, Any], feed_data: Dict[str, Any]
    ) -> None:
        feed_lang = feed_data.get("language")
        if feed_lang:
            feed_lang = feed_lang.lower()
            feed_info["lang_feed"] = feed_lang
            feed_info["languages"].add(feed_lang)
            self.stats.lang_src_feed += 1

            if feed_info["lang_http"] and feed_info["lang_http"] != feed_lang:
                self.stats.lang_mismatches += 1

    @staticmethod
    def _record_feed_recency(
        feed_info: Dict[str, Any], feed_data: Dict[str, Any], request_time: datetime
    ) -> None:
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

    def _analyze_entries(
        self, feed_info: Dict[str, Any], parsed_data: Any, request_time: datetime
    ) -> None:
        newest_date = parsed_data.get("newest_entry_date")
        oldest_date = parsed_data.get("oldest_entry_date")
        content_lengths = parsed_data.get("content_lengths", [])
        entry_langs = parsed_data.get("entry_languages", set())
        all_langs = parsed_data.get("all_languages", set())

        if entry_langs:
            self.stats.lang_src_entry += len(entry_langs)
            feed_info["languages"].update(entry_langs)
            feed_info["lang_entries"].update(entry_langs)

        if len(all_langs) > 1:
            self.stats.lang_multiple_in_feed += 1

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
            except (ValueError, TypeError, IndexError):
                pass

        feed_info["newest_entry_date"] = newest_date
        feed_info["oldest_entry_date"] = oldest_date
        feed_info["content_lengths"] = content_lengths
        for length in content_lengths:
            binned = (length // 100) * 100
            self.stats.content_length_counts[binned] = (
                self.stats.content_length_counts.get(binned, 0) + 1
            )


def _parse_request_time(request_time_str: Optional[str]) -> datetime:
    if request_time_str:
        try:
            if len(request_time_str) == 20 and request_time_str.endswith("Z"):
                return datetime.strptime(
                    request_time_str, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
            request_time = dateutil.parser.parse(request_time_str)
            if request_time.tzinfo is None:
                return request_time.replace(tzinfo=timezone.utc)
            return request_time
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


def _content_type_parts(content_type_header: str) -> tuple[str, str]:
    content_type = content_type_header.split(";")[0].strip().lower()
    charset = ""
    if ";" in content_type_header:
        parts = content_type_header.split(";")
        for part in parts[1:]:
            if "charset=" in part.lower():
                charset = part.lower().split("charset=")[1].strip().strip('"')
    return content_type, charset


def _init_feed_info(
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
        "entry_title_count": 0,
        "repeated_entry_title_count": 0,
        "repeated_entry_title_ratio": 0.0,
        "default_entry_title_count": 0,
        "content_type_profile": "unknown",
        "title": None,
        "link": None,
    }
