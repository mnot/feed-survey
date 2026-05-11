import argparse
import sys
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Mapping, Optional, cast

import lxml.etree
import requests

from feed_survey.analysis.feed_analysis import FeedAnalyzer, parse_error_label
from feed_survey.analysis.html_discovery import HtmlDiscovery
from feed_survey.analysis.stats import Stats
from feed_survey.report import generate_report
from feed_survey.report.render import default_markdown_path
from feed_survey.url import get_site, normalize_url

USER_AGENT = "feed-survey-opml/0.1"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class OpmlEntry:
    feed_url: str
    html_url: Optional[str]
    title: str


@dataclass(frozen=True)
class _Fetched:
    url: str
    response: Optional[requests.Response]
    error: Optional[Exception]


class ResponseTooLarge(RuntimeError):
    pass


class _HttpHeaders(dict[str, str]):
    def __init__(self, headers: Mapping[str, str], status_code: int) -> None:
        super().__init__(headers)
        self.status_code = status_code


class _ContentRecord:  # pylint: disable=too-few-public-methods
    def __init__(
        self, url: str, content: bytes, headers: Mapping[str, str], status_code: int
    ) -> None:
        self.headers = {
            "WARC-Target-URI": url,
            "WARC-Date": datetime.now(timezone.utc).isoformat(),
        }
        self.http_headers = _HttpHeaders(headers, status_code)
        self.reader = BytesIO(content)


Fetcher = Callable[[str, float], requests.Response]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="feed-survey-opml",
        description="Analyze feeds listed in an OPML file and render HTML/Markdown reports.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("opml", help="OPML file path or HTTP(S) URL")
    parser.add_argument(
        "-o",
        "--output",
        default="opml_report.html",
        help="Path to the output HTML report; Markdown is written next to it.",
    )
    parser.add_argument(
        "--title",
        default=argparse.SUPPRESS,
        help="Report title/crawl label. Defaults to the OPML filename or URL.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--skip-html",
        action="store_true",
        help="Do not fetch OPML url/htmlUrl pages for autodiscovery checks.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress fetch progress messages.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=32,
        help="Maximum parallel feed/page fetches.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help="Maximum bytes to download from each feed/page URL. Use 0 for no cap.",
    )
    args = parser.parse_args()

    try:
        stats = analyze_opml(
            args.opml,
            timeout=args.timeout,
            check_html=not args.skip_html,
            concurrency=args.concurrency,
            max_bytes=args.max_bytes,
            quiet=args.quiet,
        )
        title = getattr(args, "title", None) or _default_title(args.opml)
        generate_report(stats, title, args.output)
        print(
            f"Reports generated: {args.output} and {default_markdown_path(args.output)}"
        )
    except KeyboardInterrupt as exc:
        print("Interrupted; no report written.", file=sys.stderr)
        raise SystemExit(130) from exc


def analyze_opml(
    source: str,
    *,
    timeout: float = 20.0,
    check_html: bool = True,
    concurrency: int = 32,
    max_bytes: int = DEFAULT_MAX_BYTES,
    quiet: bool = False,
    fetcher: Optional[Fetcher] = None,
) -> Stats:
    active_fetcher = fetcher or (
        lambda url, request_timeout: _fetch(
            url, request_timeout, max_bytes=max(0, max_bytes)
        )
    )
    _status(f"Loading OPML: {source}", quiet)
    content = _load_opml(source, timeout, active_fetcher)
    entries = parse_opml_entries(content)
    stats = Stats()
    stats.tranco_include_subdomains = False
    html_total = len({entry.html_url for entry in entries if entry.html_url})
    _status(
        f"Found {len(entries)} unique feed URLs"
        + (f" and {html_total} HTML pages to check" if check_html else ""),
        quiet,
    )

    html_urls = _unique(entry.html_url for entry in entries if entry.html_url)
    feed_urls = [entry.feed_url for entry in entries]

    if check_html:
        for idx, fetched in enumerate(
            _fetch_many(
                "HTML",
                html_urls,
                timeout=timeout,
                concurrency=concurrency,
                quiet=quiet,
                fetcher=active_fetcher,
            ),
            1,
        ):
            _process_html_result(stats, fetched, idx, html_total, quiet)

    for idx, fetched in enumerate(
        _fetch_many(
            "feed",
            feed_urls,
            timeout=timeout,
            concurrency=concurrency,
            quiet=quiet,
            fetcher=active_fetcher,
        ),
        1,
    ):
        _process_feed_result(stats, fetched, idx, len(feed_urls), quiet)

    stats.sites_seen_count = len(stats.sites_seen)
    _status(
        f"Done: {len(stats.feed_results)} feed URLs checked, "
        f"{sum(1 for result in stats.feed_results.values() if result.get('valid'))} parsed",
        quiet,
    )
    return stats


def parse_opml_entries(content: bytes) -> list[OpmlEntry]:
    parser = lxml.etree.XMLParser(  # pylint: disable=c-extension-no-member
        resolve_entities=False, recover=True
    )
    root = lxml.etree.fromstring(  # pylint: disable=c-extension-no-member
        content, parser=parser
    )
    entries: list[OpmlEntry] = []
    seen: set[str] = set()

    outlines = cast(list[Any], root.xpath("//*[local-name()='outline']"))
    for outline in outlines:
        if not hasattr(outline, "attrib"):
            continue
        attrs = {
            str(key).lower(): str(value).strip()
            for key, value in outline.attrib.items()
        }
        feed_url = attrs.get("xmlurl")
        if not feed_url:
            continue
        feed_url = normalize_url(feed_url)
        if feed_url in seen:
            continue
        seen.add(feed_url)

        html_url = attrs.get("htmlurl") or attrs.get("url")
        entries.append(
            OpmlEntry(
                feed_url=feed_url,
                html_url=normalize_url(html_url) if html_url else None,
                title=attrs.get("title") or attrs.get("text") or "",
            )
        )
    return entries


def _fetch_many(
    label: str,
    urls: list[str],
    *,
    timeout: float,
    concurrency: int,
    quiet: bool,
    fetcher: Fetcher,
) -> Generator[_Fetched, None, None]:
    if not urls:
        return
    workers = max(1, min(concurrency, len(urls)))
    _status(f"Fetching {len(urls)} {label} URLs with concurrency {workers}", quiet)
    if workers == 1:
        for url in urls:
            yield _fetch_one(url, timeout, fetcher)
        return

    executor = ThreadPoolExecutor(max_workers=workers)
    futures: set[Future[_Fetched]] = {
        executor.submit(_fetch_one, url, timeout, fetcher) for url in urls
    }
    try:
        while futures:
            done, futures = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                yield future.result()
    except KeyboardInterrupt:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown(wait=True)


def _fetch_one(url: str, timeout: float, fetcher: Fetcher) -> _Fetched:
    try:
        return _Fetched(url=url, response=fetcher(url, timeout), error=None)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return _Fetched(url=url, response=None, error=exc)


def _process_html_result(
    stats: Stats, fetched: _Fetched, idx: int, total: int, quiet: bool
) -> None:
    _status(f"Checking HTML {idx}/{total}: {fetched.url}", quiet)
    if fetched.response is None:
        _status(f"HTML fetch failed: {fetched.url}", quiet)
        return
    _record_html_response(stats, fetched.url, fetched.response)


def _process_feed_result(
    stats: Stats, fetched: _Fetched, idx: int, total: int, quiet: bool
) -> None:
    if fetched.response is not None:
        _status(
            f"Processing feed {idx}/{total}: {fetched.url} "
            f"({len(fetched.response.content)} bytes)",
            quiet,
        )
    else:
        _status(f"Processing feed {idx}/{total}: {fetched.url}", quiet)
    if fetched.response is None:
        if fetched.error is not None:
            _status(f"Feed fetch failed: {fetched.url}", quiet)
            _record_fetch_failure(stats, fetched.url, fetched.error)
        return
    _record_feed_response(stats, fetched.url, fetched.response)


def _record_html_response(
    stats: Stats,
    url: str,
    response: requests.Response,
) -> None:
    stats.responses_processed += 1
    stats.pages_seen += 1
    stats.pages_processed += 1
    stats.sites_seen.add(get_site(response.url or url))
    content_type = _content_type(response.headers)
    stats.content_type_counts[content_type] = (
        stats.content_type_counts.get(content_type, 0) + 1
    )
    if 200 <= response.status_code < 400:
        HtmlDiscovery(stats).process(response.url or url, response.content)


def _record_feed_response(
    stats: Stats,
    url: str,
    response: requests.Response,
) -> None:
    stats.responses_processed += 1
    stats.sites_seen.add(get_site(response.url or url))
    content_type = _content_type(response.headers)
    stats.content_type_counts[content_type] = (
        stats.content_type_counts.get(content_type, 0) + 1
    )
    record = _ContentRecord(
        response.url or url,
        response.content,
        dict(response.headers),
        response.status_code,
    )
    FeedAnalyzer(stats).process(
        record,
        normalize_url(response.url or url),
        response.status_code,
        candidate_source="opml",
    )


def _record_fetch_failure(stats: Stats, url: str, exc: Exception) -> None:
    normalized = normalize_url(url)
    error_type = type(exc).__name__
    stats.feed_results[normalized] = {
        "url": normalized,
        "status": 0,
        "content_type": "",
        "valid": False,
        "format": None,
        "entries_count": 0,
        "error": str(exc),
        "error_type": parse_error_label(error_type),
        "candidate_sources": {"opml"},
    }
    stats.error_types[error_type] = stats.error_types.get(error_type, 0) + 1


def _load_opml(source: str, timeout: float, fetcher: Fetcher) -> bytes:
    if source.startswith(("http://", "https://")):
        response = fetcher(source, timeout)
        response.raise_for_status()
        return response.content
    return Path(source).read_bytes()


def _fetch(
    url: str, timeout: float, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> requests.Response:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        stream=max_bytes > 0,
    )
    if max_bytes <= 0:
        return response

    chunks: list[bytes] = []
    bytes_read = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        bytes_read += len(chunk)
        if bytes_read > max_bytes:
            response.close()
            raise ResponseTooLarge(f"Response exceeded {max_bytes} bytes")
        chunks.append(chunk)
    response._content = b"".join(chunks)  # pylint: disable=protected-access
    return response


def _content_type(headers: Mapping[str, str]) -> str:
    value = headers.get("Content-Type", "")
    return value.split(";", 1)[0].strip().lower() or "unknown"


def _default_title(source: str) -> str:
    if source.startswith(("http://", "https://")):
        return f"OPML: {source}"
    return f"OPML: {Path(source).name}"


def iter_feed_urls(entries: Iterable[OpmlEntry]) -> Iterable[str]:
    for entry in entries:
        yield entry.feed_url


def _unique(values: Iterable[Optional[str]]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _status(message: str, quiet: bool) -> None:
    if not quiet:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
