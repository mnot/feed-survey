import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import dateutil.parser

from cc_feeds.analysis import Stats
from cc_feeds.analysis.feed_analysis import parse_error_label
from cc_feeds.report.aggregate import (
    aggregate_feed_data,
    content_profile_prevalence_rows,
    extension_prevalence_rows,
    fingerprint_prevalence_rows,
    html_fingerprint_rows,
    language_prevalence_rows,
    source_fingerprint_quality_rows,
)
from cc_feeds.report.context import (
    ReportContext,
    render_report_html,
    render_report_markdown,
)
from cc_feeds.report.discovery import build_discovery_summary
from cc_feeds.report.distributions import (
    collapse_content_types,
    count_content_profiles,
    count_language_buckets,
)
from cc_feeds.report.histograms import build_recency_cdf
from cc_feeds.report.quality_summary import build_quality_summary


def generate_report(
    stats: Stats, crawl_id: str, output_path: str, markdown_path: Optional[str] = None
) -> None:
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
    errors = _feed_error_rows(stats)

    extension_prevalence = extension_prevalence_rows(all_valid_results, now)
    content_profile_prevalence = content_profile_prevalence_rows(all_valid_results, now)
    language_prevalence = language_prevalence_rows(all_valid_results, now)
    fingerprint_prevalence = fingerprint_prevalence_rows(all_valid_results, now)
    html_fingerprints = html_fingerprint_rows(
        stats.html_fingerprint_counts,
        stats.html_fingerprint_auto_counts,
    )
    context = ReportContext(
        stats=stats,
        crawl_id=crawl_id,
        aggregate=agg,
        discovery=discovery,
        quality=quality,
        content_types_collapsed=content_types_collapsed,
        content_profile_dist=content_profile_dist,
        content_profile_prevalence=content_profile_prevalence,
        lang_count_hist=lang_count_hist,
        feed_recency_cdf=feed_recency_cdf,
        entry_recency_cdf=entry_recency_cdf,
        oldest_entry_cdf=oldest_entry_cdf,
        n_zero_entry=n_zero_entry,
        max_crawl_time=max_crawl_time,
        all_valid_count=len(all_valid_results),
        discovered_count=len(discovered_results),
        formats=formats,
        languages=languages,
        language_prevalence=language_prevalence,
        fingerprint_prevalence=fingerprint_prevalence,
        html_fingerprints=html_fingerprints,
        source_fingerprint_quality=source_fingerprint_quality_rows(
            all_valid_results,
            stats.feed_source_fingerprints,
            now,
        ),
        extension_prevalence=extension_prevalence,
        errors=errors,
    )

    html = render_report_html(context)
    with open(output_path, "w", encoding="utf-8") as f_out:
        f_out.write(html)

    markdown = render_report_markdown(context)
    markdown_output_path = markdown_path or default_markdown_path(output_path)
    with open(markdown_output_path, "w", encoding="utf-8") as f_out:
        f_out.write(markdown)


def default_markdown_path(output_path: str) -> str:
    root, _ext = os.path.splitext(output_path)
    if not root:
        return f"{output_path}.md"
    return f"{root}.md"


def _feed_error_rows(stats: Stats) -> list[tuple[str, int]]:
    error_counts: Counter[str] = Counter()
    for result in stats.feed_results.values():
        if not isinstance(result, dict):
            continue
        if result.get("valid") and not result.get("error"):
            continue
        error_type = result.get("error_type")
        if not error_type:
            error = result.get("error")
            error_type = parse_error_label(error) if isinstance(error, str) else None
        if not error_type:
            error_type = f"HTTP {result.get('status')}" if result.get("status") else "Error"
        error_counts[str(error_type)] += 1
    return sorted(error_counts.items(), key=lambda item: item[1], reverse=True)
