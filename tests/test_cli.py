from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch
from requests import PreparedRequest, Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from feed_survey import opml, probe
from feed_survey.emr import finalize, split_paths
from feed_survey.report import mock


def test_split_paths_cli_limit(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    source = tmp_path / "warc.paths.txt"
    source.write_text("a.warc.gz\nb.warc.gz\nc.warc.gz\n", encoding="utf-8")
    uploads: list[list[str]] = []

    def fake_run(args: list[str], check: bool) -> None:
        uploads.append(args)
        assert check is True

    monkeypatch.setattr("feed_survey.emr.split_paths.subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["split_paths", str(source), "s3://example/chunks", "2", "2"],
    )

    split_paths.main()

    output = capsys.readouterr().out
    assert "Limited to first 2 paths." in output
    assert "Done: 2 chunks at s3://example/chunks/" in output
    assert uploads == [["aws", "s3", "sync", uploads[0][3], "s3://example/chunks/"]]


def test_finalize_cli_default(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_finalize(results_dir: str, crawl_id: str, output_path: str) -> None:
        calls.append((results_dir, crawl_id, output_path))

    monkeypatch.setattr(finalize, "finalize_mr_results", fake_finalize)
    monkeypatch.setattr("sys.argv", ["finalize", "results/test", "CC-MAIN-2026-12"])

    finalize.main()

    assert calls == [("results/test", "CC-MAIN-2026-12", "feed_survey_report.html")]


def test_mock_report_cli_default(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[object, str, str]] = []

    def fake_generate_report(stats: object, crawl_id: str, output_path: str) -> None:
        calls.append((stats, crawl_id, output_path))

    monkeypatch.setattr(
        mock,
        "build_mock_stats",
        lambda: SimpleNamespace(feed_results={}, autodiscovery_links={}),
    )
    monkeypatch.setattr(
        mock,
        "generate_report",
        fake_generate_report,
    )
    monkeypatch.setattr("sys.argv", ["mock"])

    mock.main()

    assert calls[0][1:] == (mock.CRAWL_ID, "mock_report.html")


def test_probe_html_autodiscovery(monkeypatch: MonkeyPatch) -> None:
    html = b"""
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml" title="RSS">
      <link rel="feed alternate" type="application/atom+xml" href="/atom.xml" hreflang="en">
    </head><body></body></html>
    """

    monkeypatch.setattr(
        "feed_survey.probe._fetch",
        lambda *_args, **_kwargs: SimpleNamespace(
            content=html,
            headers={"Content-Type": "text/html; charset=utf-8"},
            status_code=200,
            url="https://example.com/page",
        ),
    )

    output = probe.probe_url("https://example.com/page")

    assert "## HTML Autodiscovery" in output
    assert "https://example.com/feed.xml" in output
    assert "https://example.com/atom.xml" in output
    assert "| Links with both relations | 1 |" in output


def test_probe_html_recursive(monkeypatch: MonkeyPatch) -> None:
    html = b"""
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml" title="RSS">
    </head><body></body></html>
    """
    feed = b"""
    <rss version="2.0"><channel>
      <title>Example Feed</title>
      <link>https://example.com/</link>
    </channel></rss>
    """
    calls: list[str] = []

    def fake_fetch(url: str, *_args: object, **_kwargs: object) -> SimpleNamespace:
        calls.append(url)
        if url.endswith("/feed.xml"):
            return SimpleNamespace(
                content=feed,
                headers={"Content-Type": "application/rss+xml"},
                status_code=200,
                url="https://example.com/feed.xml",
            )
        return SimpleNamespace(
            content=html,
            headers={"Content-Type": "text/html; charset=utf-8"},
            status_code=200,
            url="https://example.com/page",
        )

    monkeypatch.setattr("feed_survey.probe._fetch", fake_fetch)

    output = probe.probe_url("https://example.com/page", recursive=True)

    assert calls == ["https://example.com/page", "https://example.com/feed.xml"]
    assert "## Recursive Feed Checks" in output
    assert "### Feed 1: https://example.com/feed.xml" in output
    assert "#### Feed Summary" in output
    assert "| Format | rss2.0 |" in output


def test_probe_feed(monkeypatch: MonkeyPatch) -> None:
    body = b"""
    <rss version="2.0"><channel>
      <title>Example Feed</title>
      <link>https://example.com/</link>
      <lastBuildDate>Fri, 01 May 2026 11:00:00 GMT</lastBuildDate>
      <item>
        <title>Entry</title>
        <link>https://example.com/entry</link>
        <pubDate>Fri, 01 May 2026 11:30:00 GMT</pubDate>
        <description>Hello</description>
      </item>
    </channel></rss>
    """

    monkeypatch.setattr(
        "feed_survey.probe._fetch",
        lambda *_args, **_kwargs: SimpleNamespace(
            content=body,
            headers={"Content-Type": "application/rss+xml"},
            status_code=200,
            url="https://example.com/feed.xml",
        ),
    )

    output = probe.probe_url("https://example.com/feed.xml")

    assert "## Feed" in output
    assert "## Language Signals" in output
    assert "## Entry Metadata" in output
    assert "| Valid RSS/Atom | yes |" in output
    assert "| Format | rss2.0 |" in output
    assert "| Entries | 1 |" in output


def test_probe_fetch_failure(monkeypatch: MonkeyPatch) -> None:
    request = PreparedRequest()
    request.prepare(method="GET", url="https://www.example.com/feed.xml")
    error = RequestsConnectionError("Failed to resolve host")
    error.request = request

    def fake_fetch(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr("feed_survey.probe._fetch", fake_fetch)

    output = probe.probe_url("https://example.com/feed.xml")

    assert "## Fetch Failed" in output
    assert "- Requested URL: `https://example.com/feed.xml`" in output
    assert "- Attempted URL: `https://www.example.com/feed.xml`" in output
    assert "- Error type: `ConnectionError`" in output
    assert "Traceback" not in output


def test_opml_parse_dedupes() -> None:
    body = b"""
    <opml version="2.0"><body>
      <outline text="Example" htmlUrl="https://example.com/" xmlUrl="https://example.com/feed.xml"/>
      <outline text="Duplicate" url="https://example.com/blog" xmlUrl="https://example.com/feed.xml"/>
      <outline text="No feed" htmlUrl="https://example.net/"/>
    </body></opml>
    """

    entries = opml.parse_opml_entries(body)

    assert entries == [
        opml.OpmlEntry(
            feed_url="https://example.com/feed.xml",
            html_url="https://example.com/",
            title="Example",
        )
    ]


def test_opml_checks_html(tmp_path: Path) -> None:
    source = tmp_path / "feeds.opml"
    source.write_text(
        """
        <opml version="2.0"><body>
          <outline
            text="Example"
            htmlUrl="https://example.com/"
            xmlUrl="https://example.com/feed.xml"
          />
        </body></opml>
        """,
        encoding="utf-8",
    )
    html = b"""
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml">
    </head><body></body></html>
    """
    feed = b"""
    <rss version="2.0"><channel>
      <title>Example Feed</title>
      <link>https://example.com/</link>
      <item><title>Entry</title><link>https://example.com/entry</link></item>
    </channel></rss>
    """

    def fake_fetch(url: str, _timeout: float) -> Response:
        if url == "https://example.com/":
            return _response(url, html, "text/html")
        return _response(url, feed, "application/rss+xml")

    stats = opml.analyze_opml(str(source), fetcher=fake_fetch)

    assert stats.responses_processed == 2
    assert stats.discovery_pages_count == 1
    assert stats.autodiscovery_links == {
        "https://example.com/feed.xml": ["example.com"]
    }
    assert stats.feed_results["https://example.com/feed.xml"]["valid"] is True
    assert stats.feed_results["https://example.com/feed.xml"]["format"] == "rss2.0"


def test_opml_cli_generates_report(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    source = tmp_path / "feeds.opml"
    source.write_text(
        '<opml version="2.0"><body><outline xmlUrl="https://example.com/feed.xml"/></body></opml>',
        encoding="utf-8",
    )
    calls: list[tuple[object, str, str]] = []

    def fake_analyze(source_arg: str, **_kwargs: object) -> object:
        assert source_arg == str(source)
        return SimpleNamespace()

    def fake_generate_report(stats: object, crawl_id: str, output_path: str) -> None:
        calls.append((stats, crawl_id, output_path))

    monkeypatch.setattr(opml, "analyze_opml", fake_analyze)
    monkeypatch.setattr(opml, "generate_report", fake_generate_report)
    monkeypatch.setattr(
        "sys.argv", ["opml", str(source), "--output", "feeds-report.html"]
    )

    opml.main()

    assert calls == [(calls[0][0], "OPML: feeds.opml", "feeds-report.html")]
    assert len(calls) == 1
    assert "Reports generated: feeds-report.html and feeds-report.md" in (
        capsys.readouterr().out
    )


def test_opml_cli_interrupt(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "feeds.opml"
    source.write_text("<opml />", encoding="utf-8")

    def fake_analyze(*_args: object, **_kwargs: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(opml, "analyze_opml", fake_analyze)
    monkeypatch.setattr("sys.argv", ["opml", str(source)])

    try:
        opml.main()
    except SystemExit as exc:
        assert exc.code == 130
    else:
        raise AssertionError("Expected SystemExit")


def test_opml_status_quiet(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    source = tmp_path / "feeds.opml"
    source.write_text(
        '<opml version="2.0"><body><outline xmlUrl="https://example.com/feed.xml"/></body></opml>',
        encoding="utf-8",
    )
    feed = b"<rss version='2.0'><channel><title>Example</title></channel></rss>"

    def fake_fetch(url: str, _timeout: float) -> Response:
        return _response(url, feed, "application/rss+xml")

    opml.analyze_opml(str(source), check_html=False, fetcher=fake_fetch)
    assert "Fetching 1 feed URLs with concurrency 1" in capsys.readouterr().err

    opml.analyze_opml(str(source), check_html=False, quiet=True, fetcher=fake_fetch)
    assert capsys.readouterr().err == ""


def test_opml_fetches_in_parallel(tmp_path: Path) -> None:
    source = tmp_path / "feeds.opml"
    source.write_text(
        """
        <opml version="2.0"><body>
          <outline xmlUrl="https://example.com/one.xml"/>
          <outline xmlUrl="https://example.com/two.xml"/>
        </body></opml>
        """,
        encoding="utf-8",
    )
    feed = b"<rss version='2.0'><channel><title>Example</title></channel></rss>"
    active = 0
    peak = 0
    barrier = Barrier(2)
    lock = Lock()

    def fake_fetch(url: str, _timeout: float) -> Response:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=5)
        with lock:
            active -= 1
        return _response(url, feed, "application/rss+xml")

    opml.analyze_opml(
        str(source),
        check_html=False,
        concurrency=2,
        quiet=True,
        fetcher=fake_fetch,
    )

    assert peak == 2


def test_opml_oversized_feed(tmp_path: Path) -> None:
    source = tmp_path / "feeds.opml"
    source.write_text(
        '<opml version="2.0"><body><outline xmlUrl="https://example.com/feed.xml"/></body></opml>',
        encoding="utf-8",
    )

    def fake_fetch(_url: str, _timeout: float) -> Response:
        raise opml.ResponseTooLarge("Response exceeded 10 bytes")

    stats = opml.analyze_opml(
        str(source),
        check_html=False,
        quiet=True,
        fetcher=fake_fetch,
    )

    result = stats.feed_results["https://example.com/feed.xml"]
    assert result["valid"] is False
    assert result["error_type"] == "ResponseTooLarge"


def _response(
    url: str, content: bytes, content_type: str, status: int = 200
) -> Response:
    response = Response()
    response.url = url
    response.status_code = status
    response._content = content  # pylint: disable=protected-access
    response.headers["Content-Type"] = content_type
    return response
