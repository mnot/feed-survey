import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

import dateutil.parser
from jinja2 import Environment, FileSystemLoader

from cc_feeds.analysis import Stats
from cc_feeds.report.aggregate import aggregate_feed_data
from cc_feeds.report.discovery import build_discovery_summary
from cc_feeds.report.distributions import (
    collapse_content_types,
    count_content_profiles,
    count_language_buckets,
    format_extension_counts,
)
from cc_feeds.report.formatting import format_number
from cc_feeds.report.histograms import build_recency_cdf, make_histogram
from cc_feeds.report.quality_summary import build_quality_summary


def generate_report(stats: Stats, crawl_id: str, output_path: str) -> None:
    # --- Feed result sets ---
    discovered_urls = set(stats.autodiscovery_links.keys())

    # All successfully parsed feeds (used for feed analysis section)
    all_valid_results: Dict[str, Any] = {
        url: res
        for url, res in stats.feed_results.items()
        if isinstance(res, dict) and res.get("valid") and not res.get("error")
    }

    # Autodiscovered subset (used for discovery charts)
    discovered_results: Dict[str, Any] = {
        url: res for url, res in all_valid_results.items() if url in discovered_urls
    }

    # Inject discovery count for display
    for url, res in all_valid_results.items():
        res["total_discovery_count"] = stats.discovery_domain_counts.get(url, 0)

    # --- Aggregate over ALL valid feeds ---
    agg = aggregate_feed_data(all_valid_results)

    feeds_with_autodiscovery = len(discovered_results)
    feeds_without_autodiscovery = len(all_valid_results) - feeds_with_autodiscovery

    content_types_collapsed = collapse_content_types(stats.content_type_counts)
    content_profile_dist = count_content_profiles(all_valid_results)
    lang_count_hist = count_language_buckets(all_valid_results)

    discovery = build_discovery_summary(stats)

    # --- Crawl time reference ---
    max_crawl_time = None
    if stats.max_crawl_time_str:
        try:
            max_crawl_time = dateutil.parser.parse(stats.max_crawl_time_str)
            if max_crawl_time.tzinfo is None:
                max_crawl_time = max_crawl_time.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass
    now = max_crawl_time or datetime.now(timezone.utc)

    # --- Recency CDFs ---
    # Feed recency uses all valid feeds (a zero-entry feed can still have a
    # feed-level updated date, so its absence is meaningful).
    # Entry-based CDFs use only feeds that actually have entries — a zero-entry
    # feed cannot have an entry date, so including it would wrongly suppress the
    # curve. We report the excluded count in the chart subtitle instead.
    feeds_with_entries = {
        url: res
        for url, res in all_valid_results.items()
        if (res.get("entries_count") or 0) > 0
    }
    n_zero_entry = len(all_valid_results) - len(feeds_with_entries)

    feed_recency_cdf = build_recency_cdf(all_valid_results, "updated_date", now)
    entry_recency_cdf = build_recency_cdf(feeds_with_entries, "newest_entry_date", now)
    oldest_entry_cdf = build_recency_cdf(feeds_with_entries, "oldest_entry_date", now)

    quality = build_quality_summary(
        all_valid_results, discovered_results, discovered_urls, now
    )

    # --- Sort & format ---
    formats = sorted(agg["formats"].items(), key=lambda x: x[1], reverse=True)
    languages = sorted(agg["languages"].items(), key=lambda x: x[1], reverse=True)
    errors = sorted(stats.error_types.items(), key=lambda x: x[1], reverse=True)
    total_errors = sum(c for _, c in errors)

    # Extensions: format as prefix:local, deduplicate, top 15
    ext_formatted = format_extension_counts(agg["extensions"])
    extensions = sorted(ext_formatted.items(), key=lambda x: x[1], reverse=True)[:15]

    # --- Template data ---
    report_stats = {
        "pages_seen": stats.pages_seen,
        "max_crawl_time": max_crawl_time,
        "sites_seen": discovery.total_sites,
        "feed_results_count": len(stats.feed_results),
        "feeds_with_autodiscovery": feeds_with_autodiscovery,
        "feeds_without_autodiscovery": feeds_without_autodiscovery,
        "formats": formats,
        "languages": languages,
        "extensions": extensions,
        "error_types": errors,
        "total_errors": total_errors,
        "feeds_with_content": agg["feeds_with_content"],
        "feeds_with_summary": agg["feeds_with_summary"],
        "feeds_with_neither": agg["feeds_with_neither"],
        "pages_with_autodiscovery": getattr(
            stats, "discovery_pages_count", len(discovery.page_to_feeds)
        ),
        "sites_with_autodiscovery": len(discovery.site_to_feeds),
        "top_n": stats.top_n,
        "feeds_sniffed": stats.feeds_sniffed,
        "total_entries": agg["total_entries"],
        "lang_src_http": agg["lang_src_http"],
        "lang_src_feed": agg["lang_src_feed"],
        "lang_src_entry": agg["lang_src_entry"],
        "lang_mismatches": agg["lang_mismatches"],
        "lang_multiple_in_feed": agg["lang_multiple_in_feed"],
        "discovery_rel_alternate": stats.discovery_rel_alternate,
        "discovery_rel_feed": stats.discovery_rel_feed,
        "discovery_rel_both_page": stats.discovery_rel_both_page,
        "discovery_multi_rel_url": stats.discovery_multi_rel_url,
        "content_types_collapsed": content_types_collapsed,
        "content_profile_dist": content_profile_dist,
        "lang_count_hist": lang_count_hist,
        "quality_hist": quality["hist"],
        "mean_quality": round(quality["mean"], 3),
    }

    env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
    env.filters["comma"] = format_number
    template = env.get_template("template.html")

    html = template.render(
        stats=report_stats,
        crawl_id=crawl_id,
        formats=formats,
        languages=languages,
        extensions=extensions,
        errors=errors,
        discovery_per_page_hist=discovery.per_page_hist,
        discovery_per_site_hist=discovery.per_site_hist,
        stacked_page_json=json.dumps(discovery.stacked_page),
        stacked_site_json=json.dumps(discovery.stacked_site),
        charsets_per_format=agg["charsets_per_format"],
        content_length_hist=make_histogram(stats.content_length_counts, bins="natural"),
        entry_counts_hist=make_histogram(agg["entry_counts"], bins="entries"),
        feed_recency_cdf=json.dumps(feed_recency_cdf),
        entry_recency_cdf=json.dumps(entry_recency_cdf),
        oldest_entry_cdf=json.dumps(oldest_entry_cdf),
        n_zero_entry=n_zero_entry,
        quality_hist=json.dumps(quality["hist"]),
        format_quality_json=json.dumps(quality["format_rows"]),
        format_quality_rows=quality["format_rows"],
        autodiscovery_quality=quality["autodiscovery"],
        no_autodiscovery_quality=quality["no_autodiscovery"],
        autodiscovery_quality_json=json.dumps(quality["autodiscovery"]),
        no_autodiscovery_quality_json=json.dumps(quality["no_autodiscovery"]),
        total_pages_f=format_number(stats.pages_seen),
        pages_with_auto_f=format_number(
            stats.discovery_pages_count
            if stats.discovery_pages_count > 0
            else len(stats.autodiscovery_links)
        ),
        zero_pages_f=format_number(discovery.zero_pages),
        total_sites_f=format_number(discovery.total_sites),
        sites_with_auto_f=format_number(len(discovery.site_to_feeds)),
        zero_sites_f=format_number(discovery.zero_sites),
        pages_with_duplicates=discovery.pages_with_duplicates,
        duplicate_prevalence_pct=discovery.duplicate_prevalence_pct,
        multi_feed_pages_total=discovery.multi_feed_pages_total,
    )

    with open(output_path, "w", encoding="utf-8") as f_out:
        f_out.write(html)
