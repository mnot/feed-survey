from cc_feeds.analysis.fast_parser import FastFeedParser


def _date_prefix(value: object) -> list[object]:
    assert isinstance(value, list)
    return value[:3]


def test_parse_atom_feed() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">
          <title>Example Atom</title>
          <link href="https://example.com/"/>
          <updated>2026-01-02T03:04:05Z</updated>
          <entry xml:lang="fr">
            <title>Entry</title>
            <updated>2026-01-03T00:00:00Z</updated>
            <content type="html">hello</content>
          </entry>
        </feed>""")

    assert result["valid"] is True
    assert result["version"] == "atom10"
    assert result["feed"]["title"] == "Example Atom"
    assert result["feed"]["link"] == "https://example.com/"
    assert result["feed"]["language"] == "en"
    assert result["entries_count"] == 1
    assert result["has_content"] is True
    assert result["content_type_profile"] == "html"
    assert result["all_languages"] == {"en", "fr"}
    assert result["entry_languages"] == {"fr"}
    assert result["error"] is None


def test_parse_rss2() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Example RSS</title>
            <link>https://example.com/</link>
            <language>en</language>
            <lastBuildDate>Fri, 02 Jan 2026 03:04:05 GMT</lastBuildDate>
            <item>
              <title>Entry</title>
              <pubDate>Sat, 03 Jan 2026 00:00:00 GMT</pubDate>
              <description>hello</description>
            </item>
          </channel>
        </rss>""")

    assert result["valid"] is True
    assert result["version"] == "rss2.0"
    assert result["feed"]["title"] == "Example RSS"
    assert result["feed"]["language"] == "en"
    assert result["entries_count"] == 1
    assert result["has_summary"] is True
    assert result["content_type_profile"] == "html"
    assert _date_prefix(result["newest_entry_date"]) == [2026, 1, 3]


def test_parse_rss1() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <rdf:RDF
            xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            xmlns="http://purl.org/rss/1.0/"
            xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:content="http://purl.org/rss/1.0/modules/content/">
          <channel>
            <title>Example RSS 1.0</title>
            <link>https://example.com/</link>
            <dc:date>2026-01-02T03:04:05Z</dc:date>
          </channel>
          <item>
            <title>Entry</title>
            <link>https://example.com/entry</link>
            <dc:date>2026-01-03T00:00:00Z</dc:date>
            <content:encoded>hello</content:encoded>
          </item>
        </rdf:RDF>""")

    assert result["valid"] is True
    assert result["version"] == "rss10"
    assert result["feed"]["title"] == "Example RSS 1.0"
    assert result["entries_count"] == 1
    assert result["has_content"] is True
    assert result["content_type_profile"] == "html"
    assert _date_prefix(result["newest_entry_date"]) == [2026, 1, 3]


def test_parse_non_xml() -> None:
    result = FastFeedParser.parse(b"this is not xml")

    assert result["valid"] is False
    assert result["error"] == "Not XML"
    assert "_content_types_seen" not in result


def test_parse_bad_xml() -> None:
    result = FastFeedParser.parse(b"<rss><channel><item></channel></rss>")

    assert result["valid"] is False
    assert result["error"]
    assert "_content_types_seen" not in result
