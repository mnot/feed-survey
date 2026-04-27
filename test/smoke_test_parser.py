from cc_feeds.fast_parser import FastFeedParser
from datetime import datetime, timezone

def test_atom():
    atom_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Example Feed</title>
      <link href="http://example.org/"/>
      <updated>2026-04-26T12:00:00Z</updated>
      <entry>
        <title>Atom Entry</title>
        <link href="http://example.org/2026/04/26/atom-entry"/>
        <updated>2026-04-26T12:00:00Z</updated>
        <content type="html">Hello &lt;b&gt;world&lt;/b&gt;</content>
      </entry>
    </feed>"""
    result = FastFeedParser.parse(atom_xml)
    print("\n--- Atom Test ---")
    print(f"Valid: {result['valid']}")
    print(f"Error: {result.get('error')}")
    print(f"Version: {result['version']}")
    print(f"Title: {result['feed']['title']}")
    print(f"Entries: {result['entries_count']}")
    print(f"Has Content: {result['has_content']}")
    print(f"Content Lengths: {result['content_lengths']}")
    assert result['valid']
    assert result['version'] == 'atom10'
    assert result['feed']['title'] == 'Example Feed'
    assert result['entries_count'] == 1

def test_rss2():
    rss_xml = b"""<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>RSS Feed</title>
        <link>http://example.org/</link>
        <item>
          <title>RSS Entry</title>
          <pubDate>Sun, 26 Apr 2026 12:00:00 GMT</pubDate>
          <description>Some summary</description>
        </item>
        <item>
          <title>Another Entry</title>
          <pubDate>Sun, 26 Apr 2026 13:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>"""
    result = FastFeedParser.parse(rss_xml)
    print("\n--- RSS 2.0 Test ---")
    print(f"Valid: {result['valid']}")
    print(f"Version: {result['version']}")
    print(f"Title: {result['feed']['title']}")
    print(f"Entries: {result['entries_count']}")
    print(f"Has Summary: {result['has_summary']}")
    print(f"Newest: {result['newest_entry_date']}")
    assert result['valid']
    assert result['version'] == 'rss2.0'
    assert result['entries_count'] == 2

def test_malformed():
    malformed = b"<rss><channel><title>Incomplete"
    result = FastFeedParser.parse(malformed)
    print("\n--- Malformed Test ---")
    print(f"Valid: {result['valid']}")
    print(f"Title: {result['feed'].get('title')}")
    # Should still be valid because of recover=True
    assert result['valid']

if __name__ == "__main__":
    test_atom()
    test_rss2()
    test_malformed()
    print("\nSmoke test PASSED!")
