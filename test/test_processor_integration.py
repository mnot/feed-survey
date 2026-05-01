import io
from datetime import datetime, timezone
from unittest.mock import MagicMock

from cc_feeds.analysis import Stats, WarcProcessor


def test_processor_integration():
    processor = WarcProcessor()

    # Mock WARC record
    record = MagicMock()
    record.headers = {"WARC-Date": "2026-04-26T12:00:00Z"}
    record.http_headers = {
        "Content-Type": "application/rss+xml",
        "Content-Language": "en",
    }

    rss_content = b"""<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Integration Feed</title>
        <link>http://example.org/</link>
        <item>
          <title>Item 1</title>
          <pubDate>Sun, 26 Apr 2026 12:00:00 GMT</pubDate>
          <description>Summary</description>
        </item>
      </channel>
    </rss>"""

    # We need to mock record.reader.read()
    record.reader.read.return_value = rss_content

    url = "http://example.org/feed.xml"
    processor._process_feed(record, url, 200)

    result = processor.stats.feed_results[url]
    print("\n--- Processor Integration Test ---")
    print(f"URL: {result['url']}")
    print(f"Format: {result['format']}")
    print(f"Title: {result['title']}")
    print(f"Entries: {result['entries_count']}")
    print(f"Has Summary: {result['has_summary']}")
    print(f"Content Lengths Histogram: {processor.stats.content_length_counts}")

    assert result["valid"]
    assert result["format"] == "rss2.0"
    assert result["entries_count"] == 1
    assert result["title"] == "Integration Feed"


if __name__ == "__main__":
    test_processor_integration()
    print("\nProcessor integration test PASSED!")
