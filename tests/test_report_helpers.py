from datetime import datetime, timezone

from cc_feeds.analysis.stats import Stats
from cc_feeds.report.discovery import build_discovery_summary
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

    assert sum(summary["hist"].values()) == 2
    assert summary["autodiscovery"]["n"] == 1
    assert summary["no_autodiscovery"]["n"] == 1
    assert [row["fmt"] for row in summary["format_rows"]] == ["rss20", "atom10"]


def test_discovery_summary_counts() -> None:
    stats = Stats()
    stats.pages_seen = 4
    stats.sites_seen_count = 3
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

    assert summary.zero_pages == 2
    assert summary.zero_sites == 1
    assert summary.per_page_hist["1"] == 1
    assert summary.per_page_hist["2"] == 1
    assert summary.pages_with_duplicates == 1
    assert summary.duplicate_prevalence_pct == 100.0
    assert "0" not in summary.stacked_page["labels"]
