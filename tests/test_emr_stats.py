from feed_survey.analysis.stats import Stats
from feed_survey.emr.finalize import _merge_summary
from feed_survey.emr.stats_wire import (
    feed_discovery_count_record,
    feed_source_fingerprint_record,
    merge_count_values,
    merge_stats_values,
    reduce_stats,
    serialize_stats,
    summary_record,
)


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
    stats.error_types = {"ParseError": 13}
    stats.html_fingerprint_counts = {"wordpress": 11}
    stats.html_fingerprint_auto_counts = {"wordpress": 8}
    stats.html_fp_pages = 12
    stats.html_fp_auto_pages = 9
    stats.discovery_domain_counts = {"https://example.com/feed.xml": 7}
    stats.top_n = 500000
    stats.tranco_include_subdomains = False

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
    assert record["error_types"] == {"ParseError": 13}
    assert record["html_fingerprint_counts"] == {"wordpress": 11}
    assert record["html_fingerprint_auto_counts"] == {"wordpress": 8}
    assert record["html_fp_pages"] == 12
    assert record["html_fp_auto_pages"] == 9
    assert "feed_source_fingerprints" not in record
    assert "discovery_domain_counts" not in record
    assert record["top_n"] == 500000
    assert record["tranco_include_subdomains"] is False


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
            "error_types": {"ParseError": 13},
            "html_fingerprint_counts": {"wordpress": 11},
            "html_fingerprint_auto_counts": {"wordpress": 8},
            "html_fp_pages": 12,
            "html_fp_auto_pages": 9,
            "feed_source_fingerprints": {
                "https://example.com/feed.xml": {"wordpress": 7}
            },
            "discovery_domain_counts": {"https://example.com/feed.xml": 8},
            "top_n": 500000,
            "tranco_include_subdomains": False,
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
    assert stats.error_types == {"ParseError": 13}
    assert stats.html_fingerprint_counts == {"wordpress": 11}
    assert stats.html_fingerprint_auto_counts == {"wordpress": 8}
    assert stats.html_fp_pages == 12
    assert stats.html_fp_auto_pages == 9
    assert stats.feed_source_fingerprints == {
        "https://example.com/feed.xml": {"wordpress": 7}
    }
    assert stats.discovery_domain_counts == {"https://example.com/feed.xml": 8}
    assert stats.top_n == 500000
    assert stats.tranco_include_subdomains is False


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
    first.discovery_link_rel_both = 15
    first.discovery_link_rel_both_page = 16
    first.discovery_pages_count = 15
    first.discovery_links_per_page_counts = {1: 16}
    first.error_types = {"ParseError": 17}
    first.discovery_domain_counts = {"https://example.com/feed.xml": 18}
    first.multi_feed_pages = {"https://example.com/": ["https://example.com/a.xml"]}
    first.html_fingerprint_counts = {"wordpress": 18}
    first.html_fingerprint_auto_counts = {"wordpress": 18}
    first.html_fp_pages = 20
    first.html_fp_auto_pages = 12
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
    second.discovery_link_rel_both = 30
    second.discovery_link_rel_both_page = 31
    second.discovery_pages_count = 30
    second.discovery_links_per_page_counts = {1: 31, 2: 32}
    second.error_types = {"ParseError": 33, "XMLSyntaxError": 34}
    second.discovery_domain_counts = {"https://example.org/feed.xml": 35}
    second.multi_feed_pages = {"https://example.org/": ["https://example.org/a.xml"]}
    second.html_fingerprint_counts = {"wordpress": 33, "drupal": 34}
    second.html_fingerprint_auto_counts = {"wordpress": 35, "drupal": 36}
    second.html_fp_pages = 40
    second.html_fp_auto_pages = 22
    second.top_n = 500000
    second.tranco_include_subdomains = False

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
    assert merged["discovery_link_rel_both"] == 45
    assert merged["discovery_link_rel_both_page"] == 47
    assert merged["discovery_pages_count"] == 45
    assert merged["discovery_links_per_page_counts"] == {"1": 47, "2": 32}
    assert merged["error_types"] == {"ParseError": 50, "XMLSyntaxError": 34}
    assert "discovery_domain_counts" not in merged
    assert merged["multi_feed_pages"] == {
        "https://example.com/": ["https://example.com/a.xml"],
        "https://example.org/": ["https://example.org/a.xml"],
    }
    assert merged["html_fingerprint_counts"] == {"wordpress": 51, "drupal": 34}
    assert merged["html_fingerprint_auto_counts"] == {
        "wordpress": 53,
        "drupal": 36,
    }
    assert merged["html_fp_pages"] == 60
    assert merged["html_fp_auto_pages"] == 34
    assert "feed_source_fingerprints" not in merged
    assert merged["top_n"] == 500000
    assert merged["tranco_include_subdomains"] is False


def test_reducer_preserves_top_n() -> None:
    first = Stats()
    first.top_n = 100000
    second = Stats()
    second.top_n = 500000
    second.tranco_include_subdomains = False

    reduced = reduce_stats(
        value for value in [serialize_stats(first), serialize_stats(second)]
    )

    assert reduced.top_n == 500000
    assert reduced.tranco_include_subdomains is False


def test_feed_source_fp_per_feed() -> None:
    merged = merge_count_values(
        value
        for value in [
            {"wordpress": 2},
            {"wordpress": 3, "drupal": 4},
        ]
    )

    assert merged == {"wordpress": 5, "drupal": 4}

    label, record = feed_source_fingerprint_record(
        "feedfp:https://example.com/feed.xml",
        (
            value
            for value in [
                {"wordpress": 2},
                {"wordpress": 3, "drupal": 4},
            ]
        ),
    )

    assert label == "feed_source_fingerprint"
    assert record == {
        "feed_url": "https://example.com/feed.xml",
        "fingerprints": {"wordpress": 5, "drupal": 4},
    }


def test_feed_discovery_count() -> None:
    label, record = feed_discovery_count_record(
        "discoverycount:https://example.com/feed.xml",
        (value for value in [2, 3, 4]),
    )

    assert label == "feed_discovery_count"
    assert record == {
        "feed_url": "https://example.com/feed.xml",
        "count": 9,
    }
