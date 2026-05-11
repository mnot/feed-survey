from datetime import datetime, timezone
from pathlib import Path

from feed_survey.analysis.stats import Stats
from feed_survey.report.aggregate import (
    aggregate_feed_data,
    content_profile_prevalence_rows,
    extension_prevalence_rows,
    feed_link_signal_rows,
    fingerprint_prevalence_rows,
    html_fingerprint_rows,
    language_prevalence_rows,
    source_fingerprint_quality_rows,
    update_cadence_cdf,
)
from feed_survey.report.context import ReportContext, build_report_stats
from feed_survey.report.discovery import DiscoverySummary, build_discovery_summary
from feed_survey.report.distributions import collapse_content_types
from feed_survey.report.histograms import build_recency_cdf
from feed_survey.report.quality_summary import build_quality_summary
from feed_survey.report.render import _feed_error_rows, generate_report


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
    assert summary["active"]["with_entries"] == 2
    assert summary["active"]["without_entries"] == 0
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
    assert all("quality_count" in row for row in summary["format_rows"])
    assert all("quality_denominator" in row for row in summary["format_rows"])
    assert all("quality_pct" in row for row in summary["format_rows"])


def test_format_quality_pct() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    stale_date = [2024, 1, 1, 0, 0, 0, 0, 0, 0]
    all_valid = {
        "https://example.com/rss-fresh.xml": _feed(fmt="rss20", days_old=0),
        "https://example.com/rss-stale.xml": {
            **_feed(fmt="rss20", days_old=0),
            "newest_entry_date": stale_date,
            "updated_date": None,
        },
        "https://example.com/atom-fresh.xml": _feed(fmt="atom10", days_old=0),
        "https://example.com/atom-stale.xml": {
            **_feed(fmt="atom10", days_old=0),
            "newest_entry_date": stale_date,
            "updated_date": None,
        },
        "https://example.com/atom-stale-2.xml": {
            **_feed(fmt="atom10", days_old=0),
            "newest_entry_date": stale_date,
            "updated_date": None,
        },
    }

    summary = build_quality_summary(all_valid, {}, set(), now)
    rows = {row["fmt"]: row for row in summary["format_rows"]}

    assert rows["rss20"]["quality_count"] == 1
    assert rows["rss20"]["quality_denominator"] == 2
    assert rows["rss20"]["quality_pct"] == 50.0
    assert rows["atom10"]["quality_count"] == 1
    assert rows["atom10"]["quality_denominator"] == 3
    assert rows["atom10"]["quality_pct"] == 33.3


def test_recency_cdf_future_dates() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    cdf = build_recency_cdf(
        {
            "https://future.example/feed.xml": {
                "updated_date": [2099, 1, 1, 0, 0, 0, 0, 0, 0]
            },
            "https://fresh.example/feed.xml": {
                "updated_date": [2026, 5, 1, 0, 0, 0, 0, 0, 0]
            },
        },
        "updated_date",
        now,
    )

    assert cdf["data"][0] == 100.0
    assert cdf["no_date"] == 1


def test_aggregate_date_coverage() -> None:
    all_valid = {
        "https://example.com/feed.xml": _feed(fmt="rss20", days_old=0),
        "https://nodates.example/feed.xml": {
            **_feed(fmt="atom10", days_old=0),
            "newest_entry_date": None,
            "oldest_entry_date": None,
            "updated_date": None,
        },
        "https://empty.example/feed.xml": {
            **_feed(fmt="rss20", days_old=0),
            "entries_count": 0,
            "newest_entry_date": None,
            "oldest_entry_date": None,
        },
    }

    aggregate = aggregate_feed_data(all_valid)

    assert aggregate["feeds_with_entries"] == 2
    assert aggregate["feeds_with_entry_dates"] == 1
    assert aggregate["feeds_with_updated_date"] == 2


def test_aggregate_repeated_links() -> None:
    all_valid = {
        "https://example.com/feed.xml": {
            **_feed(fmt="rss20", days_old=0),
            "repeated_entry_link_count": 2,
        }
    }

    aggregate = aggregate_feed_data(all_valid)

    assert aggregate["feeds_with_repeated_entry_links"] == 1


def test_extension_quality_split() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    fresh = _feed(fmt="rss20", days_old=0)
    fresh["extensions"] = {("http://purl.org/dc/elements/1.1/", "creator")}
    stale = _feed(fmt="rss20", days_old=0)
    stale["newest_entry_date"] = [2024, 1, 1, 0, 0, 0, 0, 0, 0]
    stale["updated_date"] = None
    stale["extensions"] = {("http://purl.org/dc/elements/1.1/", "creator")}

    rows = extension_prevalence_rows(
        {
            "https://fresh.example/feed.xml": fresh,
            "https://stale.example/feed.xml": stale,
        },
        now,
    )

    assert rows[0]["extension"] == "dc:creator"
    assert rows[0]["extension_prefix"] == "dc"
    assert rows[0]["extension_local"] == "creator"
    assert (
        rows[0]["extension_href"]
        == "https://www.dublincore.org/specifications/dublin-core/dces/"
    )
    assert rows[0]["all_count"] == 2
    assert rows[0]["all_pct"] == 100.0
    assert rows[0]["quality_count"] == 1
    assert rows[0]["quality_denominator"] == 1
    assert rows[0]["quality_pct"] == 100.0


def test_profile_quality_split() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    fresh_html = _feed(fmt="rss20", days_old=0, has_content=True)
    stale_plain = _feed(fmt="rss20", days_old=0, has_content=False)
    stale_plain["newest_entry_date"] = [2024, 1, 1, 0, 0, 0, 0, 0, 0]
    stale_plain["updated_date"] = None

    rows = content_profile_prevalence_rows(
        {
            "https://fresh.example/feed.xml": fresh_html,
            "https://stale.example/feed.xml": stale_plain,
        },
        now,
    )
    by_profile = {row["profile"]: row for row in rows}

    assert by_profile["html"]["all_count"] == 1
    assert by_profile["html"]["quality_count"] == 1
    assert by_profile["html"]["quality_denominator"] == 1
    assert by_profile["plain"]["all_count"] == 1
    assert by_profile["plain"]["quality_count"] == 0


def test_language_quality_split() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    fresh_en = _feed(fmt="rss20", days_old=0)
    fresh_en["languages"] = {"en"}
    stale_fr = _feed(fmt="rss20", days_old=0)
    stale_fr["languages"] = {"fr"}
    stale_fr["newest_entry_date"] = [2024, 1, 1, 0, 0, 0, 0, 0, 0]
    stale_fr["updated_date"] = None

    rows = language_prevalence_rows(
        {
            "https://fresh.example/feed.xml": fresh_en,
            "https://stale.example/feed.xml": stale_fr,
        },
        now,
    )
    by_language = {row["language"]: row for row in rows}

    assert by_language["en"]["all_count"] == 1
    assert by_language["en"]["quality_count"] == 1
    assert by_language["en"]["quality_denominator"] == 1
    assert by_language["fr"]["all_count"] == 1
    assert by_language["fr"]["quality_count"] == 0


def test_fingerprint_quality_split() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    fresh_wp = _feed(fmt="rss20", days_old=0)
    fresh_wp["fingerprints"] = {"wordpress"}
    stale_wp = _feed(fmt="rss20", days_old=0)
    stale_wp["fingerprints"] = {"wordpress"}
    stale_wp["newest_entry_date"] = [2024, 1, 1, 0, 0, 0, 0, 0, 0]
    stale_wp["updated_date"] = None

    rows = fingerprint_prevalence_rows(
        {
            "https://fresh.example/feed.xml": fresh_wp,
            "https://stale.example/feed.xml": stale_wp,
        },
        now,
    )

    assert rows[0]["fingerprint"] == "wordpress"
    assert rows[0]["all_count"] == 2
    assert rows[0]["quality_count"] == 1
    assert rows[0]["quality_denominator"] == 1


def test_signal_and_cadence_rows() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    with_signals = _feed(fmt="atom10", days_old=0)
    with_signals.update(
        {
            "has_self_link": True,
            "has_hub_link": True,
            "update_cadence_days": 1.0,
            "update_cadence_bucket": "daily",
        }
    )
    unknown_cadence = _feed(fmt="rss20", days_old=0)

    signals = feed_link_signal_rows({"a": with_signals, "b": unknown_cadence}, now)
    cadence = update_cadence_cdf({"a": with_signals, "b": unknown_cadence})

    by_signal = {row["signal"]: row for row in signals}
    assert by_signal["self/canonical URL"]["all_count"] == 1
    assert by_signal["WebSub/PubSubHubbub hub"]["all_count"] == 1
    assert cadence["data"][1] == 100.0
    assert cadence["no_cadence"] == 1


def test_html_fingerprint_rows() -> None:
    rows = html_fingerprint_rows(
        {"wordpress": 10, "drupal": 5},
        {"wordpress": 4, "drupal": 1},
        page_totals={
            "html": 20,
            "autodiscovery": 8,
            "fingerprinted": 12,
            "fingerprinted_auto": 5,
        },
    )

    assert rows[0] == {
        "fingerprint": "wordpress",
        "html_pages": 10,
        "autodiscovery_pages": 4,
        "autodiscovery_pct": 40.0,
    }
    assert rows[1] == {
        "fingerprint": "unknown",
        "html_pages": 8,
        "autodiscovery_pages": 3,
        "autodiscovery_pct": 37.5,
    }


def test_source_quality_rows() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = source_fingerprint_quality_rows(
        {
            "https://fresh.example/feed.xml": _feed(fmt="rss20", days_old=0),
            "https://stale.example/feed.xml": {
                **_feed(fmt="rss20", days_old=0),
                "newest_entry_date": [2024, 1, 1, 0, 0, 0, 0, 0, 0],
                "updated_date": None,
            },
            "https://direct.example/feed.xml": _feed(fmt="rss20", days_old=0),
        },
        {
            "https://fresh.example/feed.xml": {"wordpress": 1},
            "https://stale.example/feed.xml": {"wordpress": 1},
        },
        now,
    )

    assert rows[0]["fingerprint"] == "wordpress"
    assert rows[0]["parsed_feeds"] == 2
    assert rows[0]["quality_count"] == 1
    assert rows[0]["quality_denominator"] == 2
    assert rows[1]["fingerprint"] == "unknown"
    assert rows[1]["parsed_feeds"] == 1
    assert rows[1]["quality_count"] == 1
    assert rows[1]["quality_denominator"] == 1
    assert {row["fingerprint"] for row in rows} == {"wordpress", "unknown"}


def test_src_quality_limit_unknown() -> None:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = source_fingerprint_quality_rows(
        {
            "https://one.example/feed.xml": _feed(fmt="rss20", days_old=0),
            "https://two.example/feed.xml": _feed(fmt="rss20", days_old=0),
            "https://three.example/feed.xml": _feed(fmt="rss20", days_old=0),
        },
        {
            "https://one.example/feed.xml": {"wordpress": 1},
            "https://two.example/feed.xml": {"drupal": 1},
        },
        now,
        limit=2,
    )

    assert len(rows) == 2
    assert {row["fingerprint"] for row in rows} == {"wordpress", "unknown"}


def test_agg_http_feed_mismatch() -> None:
    all_valid = {
        "https://entry.example/feed.xml": {
            **_feed(fmt="atom10", days_old=0),
            "lang_http": "en",
            "lang_feed": "en",
            "lang_entries": {"fr"},
        },
        "https://http.example/feed.xml": {
            **_feed(fmt="rss20", days_old=0),
            "lang_http": "de",
            "lang_feed": "en",
            "lang_entries": {"en"},
        },
        "https://hreflang.example/feed.xml": {
            **_feed(fmt="atom10", days_old=0),
            "lang_http": None,
            "lang_feed": None,
            "lang_entries": set(),
            "has_hreflang": True,
        },
        "https://none.example/feed.xml": {
            **_feed(fmt="rss20", days_old=0),
            "lang_http": None,
            "lang_feed": None,
            "lang_entries": set(),
        },
    }

    aggregate = aggregate_feed_data(all_valid)

    assert aggregate["lang_src_http"] == 2
    assert aggregate["lang_src_feed"] == 2
    assert aggregate["lang_src_entry"] == 2
    assert aggregate["lang_http_feed"] == 2
    assert aggregate["lang_mismatches"] == 1
    assert aggregate["lang_multiple_entry_languages"] == 2
    assert aggregate["lang_hreflang"] == 1
    assert aggregate["lang_no_info"] == 1


def test_discovery_summary_counts() -> None:
    stats = Stats()
    stats.pages_seen = 4
    stats.content_type_counts = {"text/html": 4}
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


def test_discovery_zero_pages_html() -> None:
    stats = Stats()
    stats.pages_seen = 10
    stats.content_type_counts = {
        "text/html": 4,
        "application/rss+xml": 6,
    }
    stats.discovery_pages_count = 1
    stats.discovery_links_per_page_counts = {1: 1}
    stats.autodiscovery_links = {"https://example.com/feed.xml": ["example.com"]}

    summary = build_discovery_summary(stats)

    assert summary.zero_pages == 3


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


def test_duplicate_normalizes_title() -> None:
    stats = Stats()
    stats.multi_feed_pages = {
        "https://example.com/": [
            "https://example.com/rss.xml",
            "https://example.com/atom.xml",
        ]
    }
    stats.feed_results = {
        "https://example.com/rss.xml": {
            "valid": True,
            "link": "https://example.com/",
            "title": "Example Feed",
        },
        "https://example.com/atom.xml": {
            "valid": True,
            "link": "https://example.com/",
            "title": " example   feed ",
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
    assert collapsed["Other Non-XML"] == 5


def test_report_language_counts() -> None:
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
        "feeds_with_entries": 0,
        "feeds_with_entry_dates": 0,
        "feeds_with_updated_date": 0,
        "feeds_with_repeated_entry_titles": 0,
        "feeds_with_default_entry_titles": 0,
        "feeds_with_repeated_entry_links": 0,
        "total_entries": 0,
        "lang_src_http": 1,
        "lang_src_feed": 1,
        "lang_src_entry": 1,
        "lang_mismatches": 1,
        "lang_multiple_in_feed": 1,
        "lang_no_info": 2,
        "lang_http_feed": 3,
        "lang_hreflang": 4,
        "lang_multiple_entry_languages": 5,
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
        site_chart={},
        pages_with_duplicates=0,
        duplicate_prevalence_pct=0.0,
        multi_feed_pages_total=0,
        duplicate_format_pairs=[],
    )
    quality = {
        "hist": {},
        "mean": 0.0,
        "split_count": 0,
        "active": {
            "mean": 0.0,
            "n": 0,
            "with_entries": 0,
            "without_entries": 0,
            "pct": 0.0,
        },
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
            content_profile_prevalence=[],
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
            language_prevalence=[],
            fingerprint_prevalence=[],
            feed_link_signals=[],
            update_cadence_cdf={},
            html_fingerprints=[],
            source_fingerprint_quality=[],
            extension_prevalence=[],
            errors=[],
        )
    )

    assert report_stats["lang_src_http"] == 1
    assert report_stats["lang_src_feed"] == 1
    assert report_stats["lang_src_entry"] == 1
    assert report_stats["lang_mismatches"] == 1
    assert report_stats["lang_multiple_in_feed"] == 1
    assert report_stats["lang_no_info"] == 2
    assert report_stats["lang_http_feed"] == 3
    assert report_stats["lang_hreflang"] == 4
    assert report_stats["lang_multiple_entry_languages"] == 5
    assert report_stats["active_quality"]["n"] == 0
    assert report_stats["inactive_quality"]["n"] == 0


def test_generate_report_writes_md(tmp_path: Path) -> None:
    stats = Stats()
    stats.pages_seen = 1
    stats.max_crawl_time_str = "2026-05-01T00:00:00Z"
    stats.content_type_counts = {"application/rss+xml": 1}
    stats.feed_results = {
        "https://example.com/feed.xml": _feed(fmt="rss2.0", days_old=0)
    }

    html_path = tmp_path / "report.html"

    generate_report(stats, "CC-MAIN-2026-12", str(html_path))

    markdown_path = tmp_path / "report.md"
    assert html_path.exists()
    assert markdown_path.exists()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Web Feed Survey: CC-MAIN-2026-12" in markdown
    assert "## Feed Availability and Freshness" in markdown
    assert "No successfully parsed autodiscovered feeds were found" in markdown
    assert "source-page platform are omitted" not in markdown
    assert "No successfully parsed autodiscovered feeds were found" in (
        html_path.read_text(encoding="utf-8")
    )


def test_groups_unknown_roots() -> None:
    stats = Stats()
    stats.feed_results = {
        f"https://example.com/{idx}.xml": {
            "valid": False,
            "error": f"Unknown root tag: root{idx}",
        }
        for idx in range(17)
    }
    stats.feed_results["https://example.com/not-xml"] = {
        "valid": False,
        "error": "Not XML",
    }

    errors = dict(_feed_error_rows(stats))

    assert "Not XML" in errors
    assert "Other unknown root tags" in errors
    assert sum(1 for label in errors if label.startswith("Unknown root tag: ")) == 15
    assert sum(errors.values()) == 18
