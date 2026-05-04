import argparse
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Mapping, Optional, cast
from urllib.parse import urljoin

import lxml.html
import requests

from feed_survey.analysis.feed_analysis import FeedAnalyzer, parse_error_label
from feed_survey.analysis.formats import guess_feed_format
from feed_survey.analysis.html_discovery import HtmlDiscovery
from feed_survey.analysis.processor import (
    _feed_content_type,  # pylint: disable=protected-access
    _normalized_content_type,  # pylint: disable=protected-access
    _sniffable_content_type,  # pylint: disable=protected-access
)
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
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    print(probe_url(args.url, timeout=args.timeout))


def probe_url(url: str, timeout: float = 20.0) -> str:
    response = _fetch(url, timeout)
    content = response.content
    content_type_header = response.headers.get("Content-Type", "")
    content_type = _normalized_content_type(content_type_header)
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
                ["Sniffed feed format", sniffed_format],
            ],
        ),
        "",
    ]

    if _is_html(content_type):
        lines.extend(_html_report(response.url, content))
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


def _html_report(url: str, content: bytes) -> List[str]:
    stats = Stats()
    HtmlDiscovery(stats).process(url, content)
    links = _autodiscovery_links(url, content)
    return [
        "## HTML Autodiscovery",
        "",
        _table(
            ["Metric", "Value"],
            [
                ["Feed links found", str(len(links))],
                ["Pages with feed links", str(stats.discovery_pages_count)],
                ["rel=alternate page", _yes_no(stats.discovery_rel_alternate)],
                ["rel=feed page", _yes_no(stats.discovery_rel_feed)],
                ["Page has both rels", _yes_no(stats.discovery_rel_both_page)],
                ["Multi-rel feed URLs", str(stats.discovery_multi_rel_url)],
            ],
        ),
        "",
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
        else "No RSS/Atom autodiscovery links were found.",
        "",
    ]


def _fetch(url: str, timeout: float) -> requests.Response:
    return requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )


def _feed_report(
    url: str, content: bytes, headers: Mapping[str, str], status_code: int
) -> List[str]:
    stats = Stats()
    record = _ProbeRecord(url, content, headers, status_code)
    FeedAnalyzer(stats).process(record, normalize_url(url), status_code)
    result = next(iter(stats.feed_results.values()), {})
    score = score_feed(result)
    rows = [
        ["Valid RSS/Atom", _yes_no(bool(result.get("valid")))],
        ["Format", str(result.get("format") or "unknown")],
        ["Parse error", _parse_error(result)],
        ["Title", str(result.get("title") or "")],
        ["Link", str(result.get("link") or "")],
        ["Generator", str(result.get("feed_generator") or "")],
        ["Entries", str(result.get("entries_count") or 0)],
        ["Languages", ", ".join(sorted(result.get("languages") or [])) or "unknown"],
        ["Newest entry date", _date_value(result.get("newest_entry_date"))],
        ["Feed updated date", _date_value(result.get("updated_date"))],
        ["Content profile", str(result.get("content_type_profile") or "unknown")],
        ["Has full content", _yes_no(bool(result.get("has_content")))],
        ["Has summary", _yes_no(bool(result.get("has_summary")))],
        ["Repeated entry titles", str(result.get("repeated_entry_title_count") or 0)],
        ["Default-looking titles", str(result.get("default_entry_title_count") or 0)],
        ["Repeated entry links", str(result.get("repeated_entry_link_count") or 0)],
        ["Operational quality", f"{score:.3f}"],
        [
            f"Quality > {QUALITY_SPLIT_THRESHOLD:.1f}",
            _yes_no(score > QUALITY_SPLIT_THRESHOLD),
        ],
    ]
    extensions = sorted(format_extension(ext) for ext in result.get("extensions", []))
    fingerprints = sorted(result.get("fingerprints") or [])
    return [
        "## Feed",
        "",
        _table(["Field", "Value"], rows),
        "",
        "## Feed Extensions",
        "",
        "\n".join(f"- `{extension}`" for extension in extensions)
        if extensions
        else "No non-core feed extensions were found.",
        "",
        "## Fingerprints",
        "",
        "\n".join(f"- {fingerprint}" for fingerprint in fingerprints)
        if fingerprints
        else "No known feed fingerprints were detected.",
        "",
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


def _should_parse_as_feed(
    content_type: str, sniffed_format: str, status_code: int
) -> bool:
    if not 200 <= status_code < 400:
        return _feed_content_type(content_type)
    if _feed_content_type(content_type):
        return True
    return _sniffable_content_type(content_type) and sniffed_format != "unknown"


def _is_html(content_type: str) -> bool:
    return "text/html" in content_type


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
