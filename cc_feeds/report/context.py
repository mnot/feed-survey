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
        quality_components_json=json.dumps(quality["components"]),
        quality_components=quality["components"],
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


def render_report_markdown(context: ReportContext) -> str:
    stats = build_report_stats(context)
    total_parsed = stats["parsed_feeds"]
    lines = [
        f"# Feed Analysis Report: {context.crawl_id}",
        "",
        "Percentages describe this Common Crawl result set, not the entire Web. "
        "Common Crawl reflects what its crawler fetched, what sites allowed, and "
        "the response-type prefilter and domain/sample limits for this run.",
        "",
        "## Run Summary",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Candidate responses analyzed", format_number(stats["pages_seen"])],
                ["HTML responses analyzed", format_number(stats["html_responses"])],
                ["Unique domains", format_number(stats["sites_seen"])],
                ["Feed URL checks", format_number(stats["feed_results_count"])],
                ["Successfully parsed feeds", format_number(total_parsed)],
                ["Broken/unparseable checks", format_number(stats["unparsed_feeds"])],
                ["Parse success rate", f"{stats['parse_success_pct']:.1f}%"],
            ],
        ),
        "",
        "## Autodiscovery",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                [
                    "Pages with feed links",
                    f"{format_number(stats['pages_with_autodiscovery'])} "
                    f"({_pct(stats['pages_with_autodiscovery'], stats['html_responses'], 2)})",
                ],
                [
                    "Sites with feed links",
                    f"{format_number(stats['sites_with_autodiscovery'])} "
                    f"({_pct(stats['sites_with_autodiscovery'], stats['sites_seen'], 2)})",
                ],
                [
                    "rel=alternate pages",
                    format_number(stats["discovery_rel_alternate"]),
                ],
                ["rel=feed pages", format_number(stats["discovery_rel_feed"])],
                [
                    "Pages with both rels",
                    format_number(stats["discovery_rel_both_page"]),
                ],
                [
                    "Multi-rel feed URLs",
                    format_number(stats["discovery_multi_rel_url"]),
                ],
                [
                    "Multi-feed pages sampled",
                    format_number(context.discovery.multi_feed_pages_total),
                ],
                [
                    "Duplicate feed variant pages",
                    format_number(context.discovery.pages_with_duplicates),
                ],
            ],
        ),
        "",
        "## Feed Availability and Freshness",
        "",
        _markdown_table(
            ["Stage", "Count", "Share of feed URL checks"],
            [
                [
                    "Feed URL checks",
                    format_number(stats["feed_results_count"]),
                    "100.0%",
                ],
                [
                    "Parsed RSS/Atom",
                    format_number(stats["parsed_feeds"]),
                    _pct(stats["parsed_feeds"], stats["feed_results_count"]),
                ],
                [
                    "Recent/datable",
                    format_number(stats["active_quality"]["n"]),
                    _pct(stats["active_quality"]["n"], stats["feed_results_count"]),
                ],
                [
                    "Active with entries",
                    format_number(stats["active_quality"]["with_entries"]),
                    _pct(
                        stats["active_quality"]["with_entries"],
                        stats["feed_results_count"],
                    ),
                ],
                [
                    "Active, zero-entry",
                    format_number(stats["active_quality"]["without_entries"]),
                    _pct(
                        stats["active_quality"]["without_entries"],
                        stats["feed_results_count"],
                    ),
                ],
            ],
        ),
        "",
        "## Formats and Quality",
        "",
        f"RSS-family feeds: {format_number(stats['rss_count'])}. "
        f"Atom feeds: {format_number(stats['atom_count'])}. "
        "Denominator: successfully parsed feeds.",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                [
                    "Mean operational quality, all parsed feeds",
                    f"{stats['mean_quality']:.3f}",
                ],
                [
                    "Mean operational quality, active-only",
                    f"{stats['active_quality']['mean']:.3f}",
                ],
                [
                    "Undated parsed feeds",
                    format_number(stats["inactive_quality"]["undated"]),
                ],
                [
                    "Stale parsed feeds",
                    format_number(stats["inactive_quality"]["stale"]),
                ],
                [
                    "Feeds with repeated entry titles",
                    format_number(stats["feeds_with_repeated_entry_titles"]),
                ],
                [
                    "Feeds with default-looking entry titles",
                    format_number(stats["feeds_with_default_entry_titles"]),
                ],
            ],
        ),
        "",
        _markdown_table(
            ["Format", "Count", "Mean quality"],
            [
                [row["fmt"], format_number(row["count"]), f"{row['mean']:.3f}"]
                for row in context.quality["format_rows"][:20]
            ],
        ),
        "",
        "## Languages",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["HTTP Content-Language", format_number(stats["lang_src_http"])],
                ["Feed-level language tag", format_number(stats["lang_src_feed"])],
                [
                    "Entry language tags, distinct",
                    format_number(stats["lang_src_entry"]),
                ],
                ["HTTP/feed mismatches", format_number(stats["lang_mismatches"])],
                ["Multi-language feeds", format_number(stats["lang_multiple_in_feed"])],
            ],
        ),
        "",
        _markdown_table(
            ["Language", "Feeds"],
            [[lang, format_number(count)] for lang, count in context.languages[:20]],
        ),
        "",
        "## Parse Errors",
        "",
        _markdown_table(
            ["Error", "Count"],
            [[err, format_number(count)] for err, count in context.errors[:20]],
        ),
        "",
    ]
    return "\n".join(lines)


def build_report_stats(context: ReportContext) -> Dict[str, Any]:
    stats = context.stats
    aggregate = context.aggregate
    discovery = context.discovery
    quality = context.quality
    parsed_feeds = context.all_valid_count
    feed_results_count = len(stats.feed_results)
    feeds_without_autodiscovery = context.all_valid_count - context.discovered_count
    rss_count = sum(
        count
        for feed_format, count in context.formats
        if str(feed_format).lower().startswith("rss")
    )
    atom_count = sum(
        count
        for feed_format, count in context.formats
        if str(feed_format).lower().startswith("atom")
    )
    return {
        "pages_seen": stats.pages_seen,
        "html_responses": context.content_types_collapsed.get("HTML", 0),
        "max_crawl_time": context.max_crawl_time,
        "sites_seen": discovery.total_sites,
        "feed_results_count": feed_results_count,
        "parsed_feeds": parsed_feeds,
        "unparsed_feeds": max(0, feed_results_count - parsed_feeds),
        "parse_success_pct": (
            round(parsed_feeds / feed_results_count * 100, 1)
            if feed_results_count
            else 0.0
        ),
        "unparsed_pct": (
            round(
                max(0, feed_results_count - parsed_feeds) / feed_results_count * 100, 1
            )
            if feed_results_count
            else 0.0
        ),
        "rss_count": rss_count,
        "atom_count": atom_count,
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
        "feeds_with_entries": aggregate["feeds_with_entries"],
        "feeds_with_entry_dates": aggregate["feeds_with_entry_dates"],
        "feeds_with_updated_date": aggregate["feeds_with_updated_date"],
        "feeds_with_repeated_entry_titles": aggregate[
            "feeds_with_repeated_entry_titles"
        ],
        "feeds_with_default_entry_titles": aggregate["feeds_with_default_entry_titles"],
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
        "active_quality": quality["active"],
        "inactive_quality": quality["inactive"],
    }


def _pct(numerator: int, denominator: int, digits: int = 1) -> str:
    if not denominator:
        return f"{0.0:.{digits}f}%"
    return f"{numerator / denominator * 100:.{digits}f}%"


def _markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    escaped_headers = [_escape_markdown_cell(header) for header in headers]
    lines = [
        "| " + " | ".join(escaped_headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |"
        )
    return "\n".join(lines)


def _escape_markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
