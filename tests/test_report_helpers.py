from datetime import datetime, timezone

from cc_feeds.analysis.stats import Stats
from cc_feeds.report.context import ReportContext, build_report_stats
from cc_feeds.report.discovery import DiscoverySummary, build_discovery_summary
from cc_feeds.report.distributions import collapse_content_types
from cc_feeds.report.quality_summary import build_quality_summary


def _feed(
    *,
    fmt: str,
    days_old: int,
    entries_count: int = 10,
    has_content: bool = True,
) -> dict[str, object]:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    date = now.replace(day=max(1, now.day - days_old))
    date_list = [
        date.year,
        date.month,
        date.day,
        date.hour,
        date.minute,
        date.second,
        date.weekday(),
        0,
        0,
    ]
    return {
        "valid": True,
        "error": None,
        "format": fmt,
        "entries_count": entries_count,
        "newest_entry_date": date_list,
        "updated_date": date_list,
        "oldest_entry_date": date_list,
        "has_content": has_content,
        "has_summary": not has_content,
        "content_lengths": [1200] if has_content else [200],
        "content_type_profile": "html" if has_content else "plain",
        "lang_entries": {"en"},
        "title": "Example",
        "link": "https://example.com/",
        "lang_feed": "en",
    }


def test_quality_summary_sets() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    all_valid = {
        "https://example.com/feed.xml": _feed(fmt="rss20", days_old=0),
        "https://other.example/feed.xml": _feed(
            fmt="atom10", days_old=10, has_content=False
        ),
        "https://undated.example/feed.xml": {
            **_feed(fmt="rss20", days_old=0),
            "newest_entry_date": None,
            "updated_date": None,
        },
        "https://stale.example/feed.xml": {
            **_feed(fmt="rss20", days_old=0),
            "newest_entry_date": [2024, 1, 1, 0, 0, 0, 0, 0, 0],
            "updated_date": None,
        },
    }
    discovered = {
        "https://example.com/feed.xml": all_valid["https://example.com/feed.xml"]
    }

    summary = build_quality_summary(
        all_valid,
        discovered,
        {"https://example.com/feed.xml"},
        now,
    )

    assert sum(summary["hist"].values()) == 4
    assert summary["active"]["n"] == 2
    assert summary["active"]["mean"] > 0
    assert summary["inactive"] == {
        "n": 2,
        "undated": 1,
        "stale": 1,
        "cutoff_days": 365,
    }
    assert [row["key"] for row in summary["components"]] == [
        "recency",
        "content_richness",
        "entry_count",
        "entry_metadata",
        "feed_metadata",
    ]
    assert all(0.0 <= row["mean"] <= 1.0 for row in summary["components"])
    assert summary["autodiscovery"]["n"] == 1
    assert summary["no_autodiscovery"]["n"] == 3
    assert [row["fmt"] for row in summary["format_rows"]] == ["atom10", "rss20"]


def test_discovery_summary_counts() -> None:
    stats = Stats()
    stats.pages_seen = 4
    stats.sites_seen_count = 3
    stats.discovery_pages_count = 3
    stats.discovery_links_per_page_counts = {1: 2, 2: 1}
    stats.autodiscovery_links = {
        "https://example.com/a.xml": ["example.com"],
        "https://example.com/b.xml": ["example.com"],
        "https://other.example/feed.xml": ["other.example"],
    }
    stats.feed_results = {
        "https://example.com/a.xml": {
            "entries_count": 2,
            "valid": True,
            "link": "https://example.com/",
            "title": "Same",
        },
        "https://example.com/b.xml": {
            "entries_count": 0,
            "valid": True,
            "link": "https://example.com/",
            "title": "Same",
        },
        "https://other.example/feed.xml": {
            "entries_count": 0,
            "valid": False,
            "status": 200,
        },
    }
    stats.multi_feed_pages = {
        "https://example.com/": [
            "https://example.com/a.xml",
            "https://example.com/b.xml",
        ]
    }

    summary = build_discovery_summary(stats)

    assert summary.zero_pages == 1
    assert summary.zero_sites == 1
    assert summary.per_page_hist["1"] == 2
    assert summary.per_page_hist["2"] == 1
    assert summary.stacked_page == {"labels": ["1", "2"], "counts": [2, 1]}
    assert summary.pages_with_duplicates == 1
    assert summary.duplicate_prevalence_pct == 100.0
    assert "0" not in summary.stacked_page["labels"]


def test_duplicate_no_query() -> None:
    stats = Stats()
    stats.pages_seen = 1
    stats.multi_feed_pages = {
        "https://example.com/": [
            "https://example.com/feed.xml",
            "https://example.com/feed.xml?format=atom",
        ]
    }
    stats.feed_results = {
        "https://example.com/feed.xml": {
            "valid": True,
            "link": "https://example.com/?utm=rss",
            "title": "Example",
        },
        "https://example.com/feed.xml?format=atom": {
            "valid": True,
            "link": "https://example.com/",
            "title": "Example",
        },
    }

    summary = build_discovery_summary(stats)

    assert summary.pages_with_duplicates == 1


def test_content_types_exclude_json() -> None:
    collapsed = collapse_content_types(
        {
            "application/feed+json": 3,
            "application/json": 2,
            "application/rss+xml": 1,
        }
    )

    assert "JSON Feed" not in collapsed
    assert collapsed["RSS"] == 1
    assert collapsed["Other"] == 5


def test_report_runtime_lang_counts() -> None:
    stats = Stats()
    stats.lang_src_http = 7
    stats.lang_src_feed = 8
    stats.lang_src_entry = 9
    stats.lang_mismatches = 10
    stats.lang_multiple_in_feed = 11
    aggregate = {
        "feeds_with_content": 0,
        "feeds_with_summary": 0,
        "feeds_with_neither": 0,
        "total_entries": 0,
        "lang_src_http": 1,
        "lang_src_feed": 1,
        "lang_src_entry": 1,
        "lang_mismatches": 1,
        "lang_multiple_in_feed": 1,
    }
    discovery = DiscoverySummary(
        page_to_feeds={},
        site_to_feeds={},
        per_page_hist={},
        per_site_hist={},
        total_sites=0,
        zero_pages=0,
        zero_sites=0,
        stacked_page={},
        stacked_site={},
        pages_with_duplicates=0,
        duplicate_prevalence_pct=0.0,
        multi_feed_pages_total=0,
    )
    quality = {
        "hist": {},
        "mean": 0.0,
        "active": {"mean": 0.0, "n": 0, "pct": 0.0},
        "inactive": {"n": 0, "undated": 0, "stale": 0, "cutoff_days": 365},
        "components": [],
    }

    report_stats = build_report_stats(
        ReportContext(
            stats=stats,
            crawl_id="CC-MAIN-2026-12",
            aggregate=aggregate,
            discovery=discovery,
            quality=quality,
            content_types_collapsed={},
            content_profile_dist={},
            lang_count_hist={},
            feed_recency_cdf={},
            entry_recency_cdf={},
            oldest_entry_cdf={},
            n_zero_entry=0,
            max_crawl_time=None,
            all_valid_count=0,
            discovered_count=0,
            formats=[],
            languages=[],
            extensions=[],
            errors=[],
        )
    )

    assert report_stats["lang_src_http"] == 7
    assert report_stats["lang_src_feed"] == 8
    assert report_stats["lang_src_entry"] == 9
    assert report_stats["lang_mismatches"] == 10
    assert report_stats["lang_multiple_in_feed"] == 11
    assert report_stats["active_quality"]["n"] == 0
    assert report_stats["inactive_quality"]["n"] == 0
