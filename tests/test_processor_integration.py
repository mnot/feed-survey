from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from fastwarc.warc import WarcRecordType  # pylint: disable=no-name-in-module

from cc_feeds.analysis import WarcProcessor


class _Headers(dict[str, str]):
    status_code = 200


def test_processor_integration() -> None:
    processor = WarcProcessor()

    record = MagicMock()
    record.record_type = WarcRecordType.response
    record.headers = {
        "WARC-Date": "2026-04-26T12:00:00Z",
        "WARC-Target-URI": "http://example.org/feed.xml",
        "WARC-Identified-Payload-Type": "application/rss+xml",
    }
    record.http_headers = _Headers(
        {
            "Content-Type": "application/rss+xml",
            "Content-Language": "en",
        }
    )

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

    record.reader.read.return_value = rss_content

    processor.process_record(record)

    result: dict[str, Any] = processor.stats.feed_results["http://example.org/feed.xml"]
    request_time = result["request_time"]
    assert isinstance(request_time, datetime)
    assert request_time.tzinfo == timezone.utc
    assert result["valid"]
    assert result["format"] == "rss2.0"
    assert result["entries_count"] == 1
    assert result["title"] == "Integration Feed"
