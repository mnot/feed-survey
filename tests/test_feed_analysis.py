from datetime import datetime, timezone
from typing import Any

from feed_survey.analysis.feed_analysis import FeedAnalyzer, parse_error_label
from feed_survey.analysis.stats import Stats


class _Reader:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self, _size: int) -> bytes:
        return self.content


class _Headers(dict[str, str]):
    status_code = 200


class _Record:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.headers = {"WARC-Date": "2026-05-01T12:00:00Z"}
        self.http_headers = _Headers({"Content-Type": content_type})
        self.reader = _Reader(content)

    def parse_http(self) -> None:
        return


def test_feed_analyzer_parse_error() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)

    analyzer.process(
        _Record(b"not xml", "application/rss+xml"),
        "https://example.com/feed.xml",
        200,
    )

    result = stats.feed_results["https://example.com/feed.xml"]
    assert result["valid"] is False
    assert result["error"] == "Not XML"
    assert result["error_type"] == "Not XML"
    assert stats.error_types == {"Not XML": 1}


def test_feed_empty_counted() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)

    analyzer.process(
        _Record(b"", "application/rss+xml"),
        "https://example.com/feed.xml",
        200,
    )

    result = stats.feed_results["https://example.com/feed.xml"]
    assert result["valid"] is False
    assert result["error"] == "Empty response"
    assert result["error_type"] == "Empty response"
    assert stats.error_types == {"Empty response": 1}


def test_parse_error_label_is_brief() -> None:
    assert (
        parse_error_label(
            "XML declaration allowed only at the start of the document, "
            "line 6, column 6 (<string>, line 6)"
        )
        == "XML declaration allowed only at the start of the document"
    )


def test_feed_analyzer_valid_feed() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)
    content = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>Example</title>
      <link>https://example.com/</link>
      <lastBuildDate>Fri, 01 May 2026 11:00:00 GMT</lastBuildDate>
      <item>
        <title>Entry</title>
        <pubDate>Fri, 01 May 2026 11:30:00 GMT</pubDate>
        <description>Hello</description>
      </item>
    </channel></rss>"""

    analyzer.process(
        _Record(content, "application/rss+xml"), "https://EXAMPLE.com/feed", 200
    )

    result: dict[str, Any] = stats.feed_results["https://example.com/feed"]
    request_time = result["request_time"]
    assert isinstance(request_time, datetime)
    assert request_time.tzinfo == timezone.utc
    assert result["valid"] is True
    assert result["format"] == "rss2.0"
    assert result["entries_count"] == 1
    assert result["updated_recently"] is True
    assert result["entry_recently"] is True
    assert result["candidate_sources"] == {"feed_media_type"}
    assert stats.total_entries == 1


def test_feed_cadence_and_links() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)
    content = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Example</title>
      <link rel="self" href="https://example.com/feed.xml"/>
      <link rel="hub" href="https://hub.example/"/>
      <updated>2026-05-01T00:00:00Z</updated>
      <entry><title>One</title><updated>2026-05-01T00:00:00Z</updated></entry>
      <entry><title>Two</title><updated>2026-04-30T00:00:00Z</updated></entry>
      <entry><title>Three</title><updated>2026-04-29T00:00:00Z</updated></entry>
    </feed>"""

    analyzer.process(
        _Record(content, "text/plain"),
        "https://example.com/feed",
        200,
        candidate_source="sniffed",
    )

    result: dict[str, Any] = stats.feed_results["https://example.com/feed"]
    assert result["candidate_sources"] == {"sniffed"}
    assert result["has_self_link"] is True
    assert result["has_hub_link"] is True
    assert result["update_cadence_days"] == 1.0
    assert result["update_cadence_bucket"] == "daily"


def test_feed_generator_fingerprint() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)
    content = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>Example</title>
      <link>https://example.com/</link>
      <generator>WordPress</generator>
    </channel></rss>"""

    analyzer.process(
        _Record(content, "application/rss+xml"), "https://example.com/feed", 200
    )

    result: dict[str, Any] = stats.feed_results["https://example.com/feed"]
    assert result["feed_generator"] == "WordPress"
    assert result["fingerprints"] == {"wordpress"}


def test_feed_analyzer_hreflang() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)
    content = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Example</title>
      <link href="https://example.com/" hreflang="en"/>
      <updated>2026-05-01T11:00:00Z</updated>
    </feed>"""

    analyzer.process(
        _Record(content, "application/atom+xml"), "https://example.com/feed", 200
    )

    result: dict[str, Any] = stats.feed_results["https://example.com/feed"]
    assert result["valid"] is True
    assert result["has_hreflang"] is True
    assert result["hreflang_values"] == {"en"}


def test_entry_lang_not_feed_lang() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)
    content = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Example</title>
      <updated>2026-05-01T11:00:00Z</updated>
      <entry xml:lang="fr">
        <title>Entry</title>
        <updated>2026-05-01T11:30:00Z</updated>
        <summary>Hello</summary>
      </entry>
    </feed>"""

    analyzer.process(
        _Record(content, "application/atom+xml"), "https://example.com/feed", 200
    )

    result: dict[str, Any] = stats.feed_results["https://example.com/feed"]
    assert result["valid"] is True
    assert result["lang_feed"] is None
    assert result["lang_entries"] == {"fr"}
    assert result["languages"] == {"fr"}
    assert stats.lang_src_feed == 0
    assert stats.lang_src_entry == 1
    assert stats.lang_mismatches == 0


def test_entry_lang_no_mismatch() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)
    content = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">
      <title>Example</title>
      <updated>2026-05-01T11:00:00Z</updated>
      <entry xml:lang="fr">
        <title>Entry</title>
        <updated>2026-05-01T11:30:00Z</updated>
        <summary>Hello</summary>
      </entry>
    </feed>"""

    analyzer.process(
        _Record(content, "application/atom+xml"), "https://example.com/feed", 200
    )

    result: dict[str, Any] = stats.feed_results["https://example.com/feed"]
    assert result["valid"] is True
    assert result["lang_feed"] == "en"
    assert result["lang_entries"] == {"fr"}
    assert stats.lang_src_feed == 1
    assert stats.lang_src_entry == 1
    assert stats.lang_mismatches == 0


def test_feed_entry_langs_multi() -> None:
    stats = Stats()
    analyzer = FeedAnalyzer(stats)
    content = b"""<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Example</title>
        <link>https://example.com/</link>
        <language>en</language>
        <item xml:lang="fr">
          <title>Entry</title>
          <pubDate>Fri, 01 May 2026 11:30:00 GMT</pubDate>
          <description>Hello</description>
        </item>
      </channel>
    </rss>"""

    analyzer.process(
        _Record(content, "application/rss+xml"), "https://example.com/feed", 200
    )

    result: dict[str, Any] = stats.feed_results["https://example.com/feed"]
    assert result["valid"] is True
    assert result["all_languages"] == {"en", "fr"}
    assert stats.lang_multiple_in_feed == 1
