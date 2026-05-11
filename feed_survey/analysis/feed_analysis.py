import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import dateutil.parser

from feed_survey.analysis.fast_parser import FastFeedParser
from feed_survey.analysis.fingerprints import (
    fingerprint_feed_generator,
    fingerprint_http_headers,
)
from feed_survey.analysis.formats import guess_feed_format
from feed_survey.analysis.stats import Stats
from feed_survey.url import normalize_url

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
        *,
        candidate_source: str = "feed_media_type",
    ) -> None:
        try:
            content = record.reader.read(10 * 1024 * 1024)
        except (OSError, RuntimeError, SyntaxError, TypeError, ValueError) as exc:
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
            feed_info["candidate_sources"].add(candidate_source)
            feed_info["fingerprints"].update(
                fingerprint_http_headers(record.http_headers)
            )
            self._handle_process_error(feed_info, url, exc)
            self.stats.feed_results[url] = feed_info
            return

        self.process_content(
            record,
            url,
            status_code=status_code,
            content=content,
            request_time_str=request_time_str,
            candidate_source=candidate_source,
        )

    def process_content(
        self,
        record: Any,
        url: str,
        *,
        status_code: int,
        content: bytes,
        request_time_str: Optional[str] = None,
        candidate_source: str = "feed_media_type",
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
        feed_info["candidate_sources"].add(candidate_source)
        feed_info["fingerprints"].update(fingerprint_http_headers(record.http_headers))
        if not 200 <= status_code < 400:
            self.stats.feed_results[url] = feed_info
            return

        try:
            if not content:
                feed_info["error"] = "Empty response"
                self._record_parse_error(feed_info, self._error_type(feed_info))
                self.stats.feed_results[url] = feed_info
                return

            parsed_data = FastFeedParser.parse(content)
            if not parsed_data.get("valid"):
                err_type = self._error_type(parsed_data)
                self._record_parse_error(parsed_data, err_type)
                feed_info["error"] = parsed_data.get("error", "parse failed")
                feed_info["error_type"] = err_type
                self.stats.feed_results[url] = feed_info
                return

            self._record_http_language(record, feed_info)
            self._analyze_parsed_feed(feed_info, parsed_data, content, request_time)
        except (OSError, RuntimeError, SyntaxError, TypeError, ValueError) as exc:
            self._handle_process_error(feed_info, url, exc)

        self.stats.feed_results[url] = feed_info

    def _record_parse_error(self, parsed_data: Dict[str, Any], err_type: str) -> None:
        parsed_data["error_type"] = err_type
        self.stats.error_types[err_type] = self.stats.error_types.get(err_type, 0) + 1

    def _error_type(self, parsed_data: Dict[str, Any]) -> str:
        err = parsed_data.get("error", "parse failed")
        if not isinstance(err, str):
            return type(err).__name__
        return parse_error_label(err)

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
        feed_info["error_type"] = err_type
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
        feed_info["feed_links"] = parsed_data.get("feed_links", {})
        feed_info["feed_link_rels"] = set(feed_info["feed_links"])
        _record_feed_link_signals(feed_info)
        feed_info["has_content"] = parsed_data.get("has_content", False)
        feed_info["has_summary"] = parsed_data.get("has_summary", False)
        feed_info["content_type_profile"] = parsed_data.get(
            "content_type_profile", "unknown"
        )
        feed_info["all_languages"] = parsed_data.get("all_languages", set())
        feed_info["hreflang_values"] = parsed_data.get("hreflang_values", set())
        feed_info["has_hreflang"] = bool(feed_info["hreflang_values"])
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
        feed_info["entry_link_count"] = parsed_data.get("entry_link_count", 0)
        feed_info["repeated_entry_link_count"] = parsed_data.get(
            "repeated_entry_link_count", 0
        )
        feed_info["repeated_entry_link_ratio"] = parsed_data.get(
            "repeated_entry_link_ratio", 0.0
        )

        feed_info["entries_count"] = entries_count
        self.stats.total_entries += entries_count

        title = feed_data.get("title")
        if title:
            feed_info["title"] = title.strip()
        link = feed_data.get("link")
        if link:
            feed_info["link"] = normalize_url(link)
        generator = feed_data.get("generator")
        if generator:
            feed_info["feed_generator"] = generator.strip()
            feed_info["fingerprints"].update(fingerprint_feed_generator(generator))

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
            feed_info["all_languages"].add(feed_lang)
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
            feed_info["all_languages"].update(entry_langs)
            feed_info["lang_entries"].update(entry_langs)

        feed_info["all_languages"].update(all_langs)
        if len(feed_info["all_languages"]) > 1:
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
        _record_update_cadence(feed_info, newest_date, oldest_date)
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


def parse_error_label(error: str) -> str:
    label = error.strip().splitlines()[0]
    label = label.split(",", 1)[0].strip()
    if not label:
        return "ParseError"
    if len(label) > 160:
        return f"{label[:157]}..."
    return label


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
        "hreflang_values": set(),
        "has_hreflang": False,
        "entry_title_count": 0,
        "repeated_entry_title_count": 0,
        "repeated_entry_title_ratio": 0.0,
        "default_entry_title_count": 0,
        "entry_link_count": 0,
        "repeated_entry_link_count": 0,
        "repeated_entry_link_ratio": 0.0,
        "content_type_profile": "unknown",
        "title": None,
        "link": None,
        "feed_generator": None,
        "fingerprints": set(),
        "candidate_sources": set(),
        "feed_links": {},
        "feed_link_rels": set(),
        "has_self_link": False,
        "has_hub_link": False,
        "has_paging_link": False,
        "has_archive_link": False,
        "update_cadence_days": None,
        "update_cadence_bucket": "unknown",
    }


def _record_feed_link_signals(feed_info: Dict[str, Any]) -> None:
    rels = set(feed_info.get("feed_link_rels") or [])
    feed_info["has_self_link"] = "self" in rels
    feed_info["has_hub_link"] = "hub" in rels
    feed_info["has_paging_link"] = bool(rels & {"first", "last", "next", "prev", "previous"})
    feed_info["has_archive_link"] = bool(
        rels & {"current", "next-archive", "prev-archive"}
    )


def _record_update_cadence(
    feed_info: Dict[str, Any], newest_date: Any, oldest_date: Any
) -> None:
    entries_count = int(feed_info.get("entries_count") or 0)
    if entries_count < 2 or not newest_date or not oldest_date:
        return
    newest_dt = _date_list_to_datetime(newest_date)
    oldest_dt = _date_list_to_datetime(oldest_date)
    if not newest_dt or not oldest_dt or newest_dt <= oldest_dt:
        return
    cadence = (newest_dt - oldest_dt).total_seconds() / 86400 / (entries_count - 1)
    feed_info["update_cadence_days"] = round(cadence, 2)
    feed_info["update_cadence_bucket"] = _cadence_bucket(cadence)


def _date_list_to_datetime(value: Any) -> Optional[datetime]:
    try:
        return datetime(
            value[0],
            value[1],
            value[2],
            value[3],
            value[4],
            value[5],
            tzinfo=timezone.utc,
        )
    except (ValueError, TypeError, IndexError):
        return None


def _cadence_bucket(days: float) -> str:
    if days < 1:
        return "sub-daily"
    if days < 2:
        return "daily"
    if days < 8:
        return "weekly"
    if days < 32:
        return "monthly"
    return "slower"
