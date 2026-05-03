from cc_feeds.analysis.stats import Stats
from cc_feeds.emr.finalize import _merge_summary
from cc_feeds.emr.stats_wire import merge_stats_values, serialize_stats, summary_record


def test_summary_record_counts() -> None:
    stats = Stats()
    stats.pages_seen = 7
    stats.pages_processed = 6
    stats.feeds_sniffed = 5
    stats.total_entries = 4
    stats.lang_src_http = 3
    stats.lang_src_feed = 2
    stats.lang_src_entry = 8
    stats.lang_mismatches = 9
    stats.lang_multiple_in_feed = 10
    stats.discovery_links_per_page_counts = {1: 12, 2: 3}
    stats.html_fingerprint_counts = {"wordpress": 11}
    stats.html_fingerprint_auto_counts = {"wordpress": 8}
    stats.top_n = 500000

    record = summary_record(stats)

    assert record["pages_seen"] == 7
    assert record["pages_processed"] == 6
    assert record["feeds_sniffed"] == 5
    assert record["total_entries"] == 4
    assert record["lang_src_http"] == 3
    assert record["lang_src_feed"] == 2
    assert record["lang_src_entry"] == 8
    assert record["lang_mismatches"] == 9
    assert record["lang_multiple_in_feed"] == 10
    assert record["discovery_links_per_page_counts"] == {1: 12, 2: 3}
    assert record["html_fingerprint_counts"] == {"wordpress": 11}
    assert record["html_fingerprint_auto_counts"] == {"wordpress": 8}
    assert record["top_n"] == 500000


def test_merge_summary_counts_once() -> None:
    stats = Stats()

    _merge_summary(
        stats,
        {
            "pages_seen": 7,
            "pages_processed": 6,
            "feeds_sniffed": 5,
            "total_entries": 4,
            "lang_src_http": 3,
            "lang_src_feed": 2,
            "lang_src_entry": 8,
            "lang_mismatches": 9,
            "lang_multiple_in_feed": 10,
            "discovery_links_per_page_counts": {"1": 12, "2": 3},
            "html_fingerprint_counts": {"wordpress": 11},
            "html_fingerprint_auto_counts": {"wordpress": 8},
            "top_n": 500000,
        },
    )

    assert stats.pages_seen == 7
    assert stats.pages_processed == 6
    assert stats.feeds_sniffed == 5
    assert stats.total_entries == 4
    assert stats.lang_src_http == 3
    assert stats.lang_src_feed == 2
    assert stats.lang_src_entry == 8
    assert stats.lang_mismatches == 9
    assert stats.lang_multiple_in_feed == 10
    assert stats.discovery_links_per_page_counts == {1: 12, 2: 3}
    assert stats.html_fingerprint_counts == {"wordpress": 11}
    assert stats.html_fingerprint_auto_counts == {"wordpress": 8}
    assert stats.top_n == 500000


def test_combiner_merges_summary() -> None:
    first = Stats()
    first.pages_seen = 7
    first.pages_processed = 6
    first.feeds_sniffed = 5
    first.total_entries = 4
    first.lang_src_http = 3
    first.lang_src_feed = 2
    first.lang_src_entry = 8
    first.lang_mismatches = 9
    first.lang_multiple_in_feed = 10
    first.discovery_rel_alternate = 11
    first.discovery_rel_feed = 12
    first.discovery_rel_both_page = 13
    first.discovery_multi_rel_url = 14
    first.discovery_pages_count = 15
    first.discovery_links_per_page_counts = {1: 16}
    first.multi_feed_pages = {"https://example.com/": ["https://example.com/a.xml"]}
    first.html_fingerprint_counts = {"wordpress": 17}
    first.html_fingerprint_auto_counts = {"wordpress": 18}
    first.top_n = 100000

    second = Stats()
    second.pages_seen = 17
    second.pages_processed = 18
    second.feeds_sniffed = 19
    second.total_entries = 20
    second.lang_src_http = 21
    second.lang_src_feed = 22
    second.lang_src_entry = 23
    second.lang_mismatches = 24
    second.lang_multiple_in_feed = 25
    second.discovery_rel_alternate = 26
    second.discovery_rel_feed = 27
    second.discovery_rel_both_page = 28
    second.discovery_multi_rel_url = 29
    second.discovery_pages_count = 30
    second.discovery_links_per_page_counts = {1: 31, 2: 32}
    second.multi_feed_pages = {"https://example.org/": ["https://example.org/a.xml"]}
    second.html_fingerprint_counts = {"wordpress": 33, "drupal": 34}
    second.html_fingerprint_auto_counts = {"wordpress": 35, "drupal": 36}
    second.top_n = 500000

    merged = merge_stats_values(
        value for value in [serialize_stats(first), serialize_stats(second)]
    )

    assert merged["pages_seen"] == 24
    assert merged["pages_processed"] == 24
    assert merged["feeds_sniffed"] == 24
    assert merged["total_entries"] == 24
    assert merged["lang_src_http"] == 24
    assert merged["lang_src_feed"] == 24
    assert merged["lang_src_entry"] == 31
    assert merged["lang_mismatches"] == 33
    assert merged["lang_multiple_in_feed"] == 35
    assert merged["discovery_rel_alternate"] == 37
    assert merged["discovery_rel_feed"] == 39
    assert merged["discovery_rel_both_page"] == 41
    assert merged["discovery_multi_rel_url"] == 43
    assert merged["discovery_pages_count"] == 45
    assert merged["discovery_links_per_page_counts"] == {"1": 47, "2": 32}
    assert merged["multi_feed_pages"] == {
        "https://example.com/": ["https://example.com/a.xml"],
        "https://example.org/": ["https://example.org/a.xml"],
    }
    assert merged["html_fingerprint_counts"] == {"wordpress": 50, "drupal": 34}
    assert merged["html_fingerprint_auto_counts"] == {
        "wordpress": 53,
        "drupal": 36,
    }
    assert merged["top_n"] == 500000
