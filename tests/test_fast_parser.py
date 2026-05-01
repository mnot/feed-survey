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


def test_atom_feed_link_prefers_alternate_over_self() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Example Atom</title>
          <link rel="self" href="https://example.com/feed.xml"/>
          <link rel="alternate" href="https://example.com/"/>
          <updated>2026-01-02T03:04:05Z</updated>
        </feed>""")

    assert result["valid"] is True
    assert result["feed"]["link"] == "https://example.com/"


def test_atom_xhtml_content_counts_descendant_text() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Example Atom</title>
          <updated>2026-01-02T03:04:05Z</updated>
          <entry>
            <title>Entry</title>
            <updated>2026-01-03T00:00:00Z</updated>
            <content type="xhtml">
              <div xmlns="http://www.w3.org/1999/xhtml">hello <b>world</b></div>
            </content>
          </entry>
        </feed>""")

    assert result["valid"] is True
    assert result["content_type_profile"] == "xhtml"
    assert result["content_lengths"]
    assert result["content_lengths"][0] >= len("hello world")


def test_atom_summary_type_contributes_to_content_profile() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Example Atom</title>
          <updated>2026-01-02T03:04:05Z</updated>
          <entry>
            <title>Entry</title>
            <updated>2026-01-03T00:00:00Z</updated>
            <summary type="html">&lt;p&gt;hello&lt;/p&gt;</summary>
          </entry>
        </feed>""")

    assert result["valid"] is True
    assert result["has_summary"] is True
    assert result["content_type_profile"] == "html"


def test_atom_updated_date_preferred_over_published() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Example Atom</title>
          <published>2025-01-02T00:00:00Z</published>
          <updated>2026-01-02T00:00:00Z</updated>
          <entry>
            <title>Entry</title>
            <published>2025-01-03T00:00:00Z</published>
            <updated>2026-01-03T00:00:00Z</updated>
          </entry>
        </feed>""")

    assert result["valid"] is True
    assert _date_prefix(result["feed"]["updated_parsed"]) == [2026, 1, 2]
    assert _date_prefix(result["newest_entry_date"]) == [2026, 1, 3]


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
    assert result["content_type_profile"] == "plain"
    assert _date_prefix(result["newest_entry_date"]) == [2026, 1, 3]


def test_rss_description_with_markup_counts_as_html() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Example RSS</title>
            <link>https://example.com/</link>
            <item>
              <title>Entry</title>
              <description>&lt;p&gt;hello&lt;/p&gt;</description>
            </item>
          </channel>
        </rss>""")

    assert result["valid"] is True
    assert result["has_summary"] is True
    assert result["content_type_profile"] == "html"


def test_rss_channel_last_build_date_preferred_over_pub_date() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Example RSS</title>
            <link>https://example.com/</link>
            <pubDate>Fri, 02 Jan 2026 00:00:00 GMT</pubDate>
            <lastBuildDate>Sat, 03 Jan 2026 00:00:00 GMT</lastBuildDate>
          </channel>
        </rss>""")

    assert result["valid"] is True
    assert _date_prefix(result["feed"]["updated_parsed"]) == [2026, 1, 3]


def test_rss_channel_dc_date_sets_feed_updated_date() -> None:
    result = FastFeedParser.parse(b"""<?xml version="1.0"?>
        <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
          <channel>
            <title>Example RSS</title>
            <link>https://example.com/</link>
            <dc:date>2026-01-04T00:00:00Z</dc:date>
          </channel>
        </rss>""")

    assert result["valid"] is True
    assert _date_prefix(result["feed"]["updated_parsed"]) == [2026, 1, 4]


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
