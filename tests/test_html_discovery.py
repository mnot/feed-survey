from cc_feeds.analysis.html_discovery import HtmlDiscovery
from cc_feeds.analysis.stats import Stats


def test_discovers_feed_links() -> None:
    stats = Stats()
    discovery = HtmlDiscovery(stats)

    discovery.process(
        "https://Example.COM/articles/",
        b"""
        <html><head>
          <link rel="alternate" type="application/rss+xml" href="/feed.xml">
          <link rel="feed" type="application/atom+xml" href="https://feeds.example.com/a">
          <link rel="stylesheet" href="/style.css">
        </head><body></body></html>
        """,
    )

    assert stats.discovery_pages_count == 1
    assert stats.discovery_rel_alternate == 1
    assert stats.discovery_rel_feed == 1
    assert stats.discovery_rel_both_page == 1
    assert stats.discovery_multi_rel_url == 0
    assert stats.discovery_links_per_page_counts == {2: 1}
    assert stats.multi_feed_pages == {
        "https://Example.COM/articles/": [
            "https://example.com/feed.xml",
            "https://feeds.example.com/a",
        ]
    }
    assert stats.autodiscovery_links["https://example.com/feed.xml"] == ["example.com"]
    assert stats.discovery_domain_counts["https://example.com/feed.xml"] == 1


def test_discovers_rel_tokens() -> None:
    stats = Stats()
    discovery = HtmlDiscovery(stats)

    discovery.process(
        "https://example.com/",
        b"""
        <html><head>
          <link rel="alternate feed" type="application/rss+xml; charset=utf-8"
                href="/rss.xml">
          <link rel="feed" type="application/rdf+xml" href="/rss1.rdf">
        </head></html>
        """,
    )

    assert stats.discovery_pages_count == 1
    assert stats.discovery_rel_alternate == 1
    assert stats.discovery_rel_feed == 1
    assert stats.discovery_rel_both_page == 1
    assert stats.discovery_multi_rel_url == 1
    assert stats.discovery_links_per_page_counts == {2: 1}
    assert set(stats.autodiscovery_links) == {
        "https://example.com/rss.xml",
        "https://example.com/rss1.rdf",
    }


def test_discovers_type_whitespace() -> None:
    stats = Stats()
    discovery = HtmlDiscovery(stats)

    discovery.process(
        "https://example.com/",
        b"""
        <html><head>
          <link rel="alternate" type = "application/rss+xml" href="/feed.xml">
        </head></html>
        """,
    )

    assert stats.discovery_pages_count == 1
    assert set(stats.autodiscovery_links) == {"https://example.com/feed.xml"}


def test_discovers_rel_whitespace() -> None:
    stats = Stats()
    discovery = HtmlDiscovery(stats)

    discovery.process(
        "https://example.com/",
        b"""
        <html><head>
          <link rel = "alternate" type="application/rss+xml" href="/feed.xml">
        </head></html>
        """,
    )

    assert stats.discovery_pages_count == 1
    assert set(stats.autodiscovery_links) == {"https://example.com/feed.xml"}


def test_ignores_pages_no_feeds() -> None:
    stats = Stats()
    discovery = HtmlDiscovery(stats)

    discovery.process(
        "https://example.com/",
        b'<html><head><link rel="stylesheet" href="/style.css"></head></html>',
    )

    assert stats.discovery_pages_count == 0
    assert stats.autodiscovery_links == {}


def test_ignores_json_feed_links() -> None:
    stats = Stats()
    discovery = HtmlDiscovery(stats)

    discovery.process(
        "https://example.com/",
        b"""
        <html><head>
          <link rel="alternate" type="application/feed+json" href="/feed.json">
        </head></html>
        """,
    )

    assert stats.discovery_pages_count == 0
    assert stats.autodiscovery_links == {}
