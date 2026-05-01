from cc_feeds.analysis.stats import Stats
from cc_feeds.emr.finalize import _merge_summary
from cc_feeds.emr.stats_wire import summary_record


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
    assert stats.top_n == 500000
