import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader

from cc_feeds.analysis import Stats
from cc_feeds.report.discovery import DiscoverySummary
from cc_feeds.report.formatting import format_number
from cc_feeds.report.histograms import make_histogram


@dataclass(frozen=True)
class ReportContext:
    stats: Stats
    crawl_id: str
    aggregate: Dict[str, Any]
    discovery: DiscoverySummary
    quality: Dict[str, Any]
    content_types_collapsed: Dict[str, int]
    content_profile_dist: Dict[str, int]
    lang_count_hist: Dict[str, int]
    feed_recency_cdf: Dict[str, Any]
    entry_recency_cdf: Dict[str, Any]
    oldest_entry_cdf: Dict[str, Any]
    n_zero_entry: int
    max_crawl_time: Optional[datetime]
    all_valid_count: int
    discovered_count: int
    formats: List[Tuple[str, int]]
    languages: List[Tuple[str, int]]
    extensions: List[Tuple[str, int]]
    errors: List[Tuple[str, int]]


def render_report_html(context: ReportContext) -> str:
    stats = context.stats
    aggregate = context.aggregate
    discovery = context.discovery
    quality = context.quality

    env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
    env.filters["comma"] = format_number
    template = env.get_template("template.html")

    report_stats = build_report_stats(context)

    return template.render(
        stats=report_stats,
        crawl_id=context.crawl_id,
        formats=context.formats,
        languages=context.languages,
        extensions=context.extensions,
        errors=context.errors,
        discovery_per_page_hist=discovery.per_page_hist,
        discovery_per_site_hist=discovery.per_site_hist,
        stacked_page_json=json.dumps(discovery.stacked_page),
        stacked_site_json=json.dumps(discovery.stacked_site),
        charsets_per_format=aggregate["charsets_per_format"],
        content_length_hist=make_histogram(stats.content_length_counts, bins="natural"),
        entry_counts_hist=make_histogram(aggregate["entry_counts"], bins="entries"),
        feed_recency_cdf=json.dumps(context.feed_recency_cdf),
        entry_recency_cdf=json.dumps(context.entry_recency_cdf),
        oldest_entry_cdf=json.dumps(context.oldest_entry_cdf),
        n_zero_entry=context.n_zero_entry,
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


def build_report_stats(context: ReportContext) -> Dict[str, Any]:
    stats = context.stats
    aggregate = context.aggregate
    discovery = context.discovery
    quality = context.quality
    feeds_without_autodiscovery = context.all_valid_count - context.discovered_count
    return {
        "pages_seen": stats.pages_seen,
        "max_crawl_time": context.max_crawl_time,
        "sites_seen": discovery.total_sites,
        "feed_results_count": len(stats.feed_results),
        "feeds_with_autodiscovery": context.discovered_count,
        "feeds_without_autodiscovery": feeds_without_autodiscovery,
        "formats": context.formats,
        "languages": context.languages,
        "extensions": context.extensions,
        "error_types": context.errors,
        "total_errors": sum(count for _, count in context.errors),
        "feeds_with_content": aggregate["feeds_with_content"],
        "feeds_with_summary": aggregate["feeds_with_summary"],
        "feeds_with_neither": aggregate["feeds_with_neither"],
        "pages_with_autodiscovery": getattr(
            stats, "discovery_pages_count", len(discovery.page_to_feeds)
        ),
        "sites_with_autodiscovery": len(discovery.site_to_feeds),
        "top_n": stats.top_n,
        "feeds_sniffed": stats.feeds_sniffed,
        "total_entries": aggregate["total_entries"],
        "lang_src_http": stats.lang_src_http,
        "lang_src_feed": stats.lang_src_feed,
        "lang_src_entry": stats.lang_src_entry,
        "lang_mismatches": stats.lang_mismatches,
        "lang_multiple_in_feed": stats.lang_multiple_in_feed,
        "discovery_rel_alternate": stats.discovery_rel_alternate,
        "discovery_rel_feed": stats.discovery_rel_feed,
        "discovery_rel_both_page": stats.discovery_rel_both_page,
        "discovery_multi_rel_url": stats.discovery_multi_rel_url,
        "content_types_collapsed": context.content_types_collapsed,
        "content_profile_dist": context.content_profile_dist,
        "lang_count_hist": context.lang_count_hist,
        "quality_hist": quality["hist"],
        "mean_quality": round(quality["mean"], 3),
    }
