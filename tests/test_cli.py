from pathlib import Path
from types import SimpleNamespace

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from feed_survey import probe
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
