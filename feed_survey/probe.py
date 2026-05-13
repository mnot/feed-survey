import argparse
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, Iterable, List, Mapping, Optional, cast
from urllib.parse import urljoin

import lxml.html
import requests
from requests.exceptions import RequestException

from feed_survey.analysis.content_types import (
    feed_content_type,
    normalized_content_type,
    sniffable_content_type,
)
from feed_survey.analysis.feed_analysis import FeedAnalyzer, parse_error_label
from feed_survey.analysis.formats import guess_feed_format
from feed_survey.analysis.html_discovery import HtmlDiscovery
from feed_survey.analysis.stats import Stats
from feed_survey.report.formatting import format_extension
from feed_survey.report.quality import QUALITY_SPLIT_THRESHOLD, score_feed
from feed_survey.url import normalize_url

USER_AGENT = "feed-survey-url-probe/0.1"


class _HttpHeaders(dict[str, str]):
    def __init__(self, headers: Mapping[str, str], status_code: int) -> None:
        super().__init__(headers)
        self.status_code = status_code


class _ProbeRecord:  # pylint: disable=too-few-public-methods
    def __init__(
        self, url: str, content: bytes, headers: Mapping[str, str], status_code: int
    ) -> None:
        self.headers = {
            "WARC-Target-URI": url,
            "WARC-Date": datetime.now(timezone.utc).isoformat(),
        }
        self.http_headers = _HttpHeaders(headers, status_code)
        self.reader = BytesIO(content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch one URL and report feed/autodiscovery diagnostics as Markdown."
    )
    parser.add_argument("url", help="URL to fetch and inspect")
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="For HTML pages, also fetch and inspect autodiscovered feed URLs.",
    )
    parser.add_argument(
        "--max-feeds",
        type=int,
        default=10,
        help="Maximum autodiscovered feeds to fetch with --recursive.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    print(
        probe_url(
            args.url,
            timeout=args.timeout,
            recursive=args.recursive,
            max_feeds=args.max_feeds,
        )
    )


def probe_url(
    url: str,
    timeout: float = 20.0,
    *,
    recursive: bool = False,
    max_feeds: int = 10,
) -> str:
    try:
        response = _fetch(url, timeout)
    except RequestException as exc:
        return "\n".join(_fetch_failure_report(url, exc))

    content = response.content
    content_type_header = response.headers.get("Content-Type", "")
    content_type = normalized_content_type(content_type_header)
    sniffed_format = guess_feed_format(content[:4096])

    lines = [
        f"# Feed Survey URL Probe: {url}",
        "",
        "## HTTP",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Final URL", response.url],
                ["Status", str(response.status_code)],
                ["Content-Type", content_type_header or "unknown"],
                ["Normalized Content-Type", content_type or "unknown"],
                ["Bytes fetched", str(len(content))],
                ["Sniffed RSS/Atom format", sniffed_format],
                [
                    "Classification",
                    _classification(content_type, sniffed_format, response.status_code),
                ],
            ],
        ),
        "",
    ]

    if _is_html(content_type):
        links = _autodiscovery_links(response.url, content)
        lines.extend(_html_report(response.url, content, links))
        if recursive:
            lines.extend(_recursive_feed_reports(links, timeout, max_feeds))
    elif _should_parse_as_feed(content_type, sniffed_format, response.status_code):
        lines.extend(
            _feed_report(
                response.url, content, dict(response.headers), response.status_code
            )
        )
    else:
        lines.extend(
            [
                "## Classification",
                "",
                "This response was not treated as a feed. It has no exact RSS/Atom "
                "media type and did not sniff as RSS/Atom.",
                "",
            ]
        )

    return "\n".join(lines)


def _html_report(url: str, content: bytes, links: List[Dict[str, str]]) -> List[str]:
    stats = Stats()
    HtmlDiscovery(stats).process(url, content)
    return [
        "## HTML Autodiscovery",
        "",
        "RSS/Atom autodiscovery links are taken from `<link>` elements with "
        "`rel=alternate`, `rel=feed`, or both, and an RSS/Atom media type.",
        "",
        _table(
            ["Metric", "Value"],
            [
                ["Feed links found", str(len(links))],
                ["Page has feed links", _yes_no(stats.discovery_pages_count)],
                ["Page uses rel=alternate", _yes_no(stats.discovery_rel_alternate)],
                ["Page uses rel=feed", _yes_no(stats.discovery_rel_feed)],
                ["Page uses both relations", _yes_no(stats.discovery_rel_both_page)],
                ["Links with both relations", str(stats.discovery_multi_rel_url)],
            ],
        ),
        "",
        (
            _table(
                ["URL", "rel", "type", "title", "hreflang"],
                [
                    [
                        link["href"],
                        link["rel"],
                        link["type"],
                        link["title"],
                        link["hreflang"],
                    ]
                    for link in links
                ],
            )
            if links
            else "No RSS/Atom autodiscovery links were found."
        ),
        "",
    ]


def _fetch(url: str, timeout: float) -> requests.Response:
    return requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )


def _recursive_feed_reports(
    links: List[Dict[str, str]], timeout: float, max_feeds: int
) -> List[str]:
    feed_urls = list(_unique_link_urls(links))[: max(0, max_feeds)]
    lines = [
        "## Recursive Feed Checks",
        "",
    ]
    if not feed_urls:
        lines.extend(["No autodiscovered feed URLs to check.", ""])
        return lines

    if len(feed_urls) < len(set(link["href"] for link in links)):
        lines.extend(
            [
                f"Checking the first {len(feed_urls)} unique autodiscovered feed URLs.",
                "",
            ]
        )

    for idx, feed_url in enumerate(feed_urls, 1):
        lines.extend([f"### Feed {idx}: {feed_url}", ""])
        try:
            response = _fetch(feed_url, timeout)
        except RequestException as exc:
            lines.extend(_fetch_failure_section(feed_url, exc, heading_level=4))
            continue
        lines.extend(
            _feed_report(
                response.url,
                response.content,
                dict(response.headers),
                response.status_code,
                heading_level=4,
            )
        )
    return lines


def _fetch_failure_report(url: str, exc: RequestException) -> List[str]:
    return [
        f"# Feed Survey URL Probe: {url}",
        "",
        *_fetch_failure_section(url, exc, heading_level=2),
    ]


def _fetch_failure_section(
    url: str, exc: RequestException, *, heading_level: int
) -> List[str]:
    heading = "#" * heading_level
    return [
        f"{heading} Fetch Failed",
        "",
        f"- Requested URL: `{_escape(url)}`",
        f"- Attempted URL: `{_escape(_attempted_url(exc))}`",
        f"- Error type: `{type(exc).__name__}`",
        f"- Error: {_escape(_compact_error(exc))}",
        "",
    ]


def _attempted_url(exc: RequestException) -> str:
    if exc.request is not None:
        return str(exc.request.url)
    return ""


def _compact_error(exc: RequestException) -> str:
    return " ".join(str(exc).split())


def _feed_report(
    url: str,
    content: bytes,
    headers: Mapping[str, str],
    status_code: int,
    *,
    heading_level: int = 2,
) -> List[str]:
    stats = Stats()
    record = _ProbeRecord(url, content, headers, status_code)
    FeedAnalyzer(stats).process(record, normalize_url(url), status_code)
    result = next(iter(stats.feed_results.values()), {})
    score = score_feed(result)
    heading = "#" * heading_level
    return [
        f"{heading} Feed Summary",
        "",
        _table(["Field", "Value"], _feed_summary_rows(result, score)),
        "",
        f"{heading} Language Signals",
        "",
        _table(["Signal", "Value"], _feed_language_rows(result)),
        "",
        f"{heading} Entry Metadata",
        "",
        _table(["Signal", "Value"], _feed_entry_rows(result)),
        "",
        f"{heading} Feed Extensions",
        "",
        _bullet_list(
            f"`{extension}`"
            for extension in sorted(
                format_extension(ext) for ext in result.get("extensions", [])
            )
        )
        or "No non-core feed extensions were found.",
        "",
        f"{heading} Fingerprints",
        "",
        _bullet_list(sorted(result.get("fingerprints") or []))
        or "No known feed fingerprints were detected.",
        "",
    ]


def _feed_summary_rows(result: Dict[str, Any], score: float) -> List[List[str]]:
    return [
        ["Valid RSS/Atom", _yes_no(bool(result.get("valid")))],
        ["Format", str(result.get("format") or "unknown")],
        ["Parse error", _parse_error(result)],
        ["HTTP Content-Type", str(result.get("content_type") or "unknown")],
        ["Title", str(result.get("title") or "")],
        ["Link", str(result.get("link") or "")],
        ["Generator", str(result.get("feed_generator") or "")],
        ["Entries", str(result.get("entries_count") or 0)],
        ["Newest entry date", _date_value(result.get("newest_entry_date"))],
        ["Feed updated date", _date_value(result.get("updated_date"))],
        ["Content profile", str(result.get("content_type_profile") or "unknown")],
        ["Operational quality", f"{score:.3f}"],
        [
            f"High quality (> {QUALITY_SPLIT_THRESHOLD:.1f})",
            _yes_no(score > QUALITY_SPLIT_THRESHOLD),
        ],
    ]


def _feed_language_rows(result: Dict[str, Any]) -> List[List[str]]:
    return [
        [
            "All languages",
            ", ".join(sorted(result.get("languages") or [])) or "unknown",
        ],
        ["HTTP Content-Language", str(result.get("lang_http") or "")],
        ["Feed-level language", str(result.get("lang_feed") or "")],
        [
            "Entry-level languages",
            ", ".join(sorted(result.get("lang_entries") or [])) or "",
        ],
        [
            "Atom hreflang values",
            ", ".join(sorted(result.get("hreflang_values") or [])) or "",
        ],
        [
            "HTTP/feed language mismatch",
            _yes_no(
                bool(
                    result.get("lang_http")
                    and result.get("lang_feed")
                    and result.get("lang_http") != result.get("lang_feed")
                )
            ),
        ],
    ]


def _feed_entry_rows(result: Dict[str, Any]) -> List[List[str]]:
    return [
        ["Has full content", _yes_no(bool(result.get("has_content")))],
        ["Has summary", _yes_no(bool(result.get("has_summary")))],
        ["Entry title count", str(result.get("entry_title_count") or 0)],
        ["Repeated entry titles", str(result.get("repeated_entry_title_count") or 0)],
        [
            "Default-looking entry titles",
            str(result.get("default_entry_title_count") or 0),
        ],
        ["Entry link count", str(result.get("entry_link_count") or 0)],
        ["Repeated entry links", str(result.get("repeated_entry_link_count") or 0)],
    ]


def _autodiscovery_links(url: str, content: bytes) -> List[Dict[str, str]]:
    try:
        doc = lxml.html.fromstring(
            content, parser=lxml.html.HTMLParser(recover=True, encoding="utf-8")
        )
    except (LookupError, RuntimeError, SyntaxError, TypeError, ValueError):
        return []

    rows = []
    links = doc.xpath("//link[@rel]")
    if not isinstance(links, list):
        return []

    for link in cast(List[Any], links):
        if not hasattr(link, "get"):
            continue
        rel = str(link.get("rel", "")).lower()
        rel_tokens = set(rel.split())
        if not rel_tokens & {"alternate", "feed"}:
            continue
        link_type = str(link.get("type", "")).lower()
        if (
            "rss+xml" not in link_type
            and "atom+xml" not in link_type
            and "rdf+xml" not in link_type
        ):
            continue
        href = link.get("href")
        if not href:
            continue
        rows.append(
            {
                "href": normalize_url(urljoin(url, str(href))),
                "rel": " ".join(sorted(rel_tokens & {"alternate", "feed"})),
                "type": link_type,
                "title": str(link.get("title") or ""),
                "hreflang": str(link.get("hreflang") or ""),
            }
        )
    return rows


def _unique_link_urls(links: Iterable[Dict[str, str]]) -> Iterable[str]:
    seen = set()
    for link in links:
        href = link["href"]
        if href in seen:
            continue
        seen.add(href)
        yield href


def _should_parse_as_feed(
    content_type: str, sniffed_format: str, status_code: int
) -> bool:
    if not 200 <= status_code < 400:
        return feed_content_type(content_type)
    if feed_content_type(content_type):
        return True
    return sniffable_content_type(content_type) and sniffed_format != "unknown"


def _is_html(content_type: str) -> bool:
    return "text/html" in content_type


def _classification(content_type: str, sniffed_format: str, status_code: int) -> str:
    if _is_html(content_type):
        return "HTML page"
    if _should_parse_as_feed(content_type, sniffed_format, status_code):
        if feed_content_type(content_type):
            return "RSS/Atom feed media type"
        return "sniffed RSS/Atom feed"
    return "not feed-like"


def _parse_error(result: Dict[str, Any]) -> str:
    error = result.get("error")
    if not error:
        return ""
    return parse_error_label(str(error))


def _date_value(value: Optional[List[int]]) -> str:
    if not value:
        return ""
    return "-".join(str(part).zfill(2) for part in value[:3])


def _yes_no(value: object) -> str:
    return "yes" if value else "no"


def _bullet_list(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _table(headers: List[str], rows: List[List[str]]) -> str:
    lines = [
        "| " + " | ".join(_escape(cell) for cell in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_escape(cell) for cell in row) + " |")
    return "\n".join(lines)


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    main()
