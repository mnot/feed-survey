import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader

from feed_survey.analysis import Stats
from feed_survey.report.discovery import DiscoverySummary
from feed_survey.report.formatting import format_number
from feed_survey.report.histograms import make_histogram
from feed_survey.report.quality import QUALITY_SPLIT_THRESHOLD
from feed_survey.tranco import tranco_list_label


@dataclass(frozen=True)
class ReportContext:
    stats: Stats
    crawl_id: str
    aggregate: Dict[str, Any]
    discovery: DiscoverySummary
    quality: Dict[str, Any]
    content_types_collapsed: Dict[str, int]
    content_profile_dist: Dict[str, int]
    content_profile_prevalence: List[Dict[str, Any]]
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
    language_prevalence: List[Dict[str, Any]]
    fingerprint_prevalence: List[Dict[str, Any]]
    feed_link_signals: List[Dict[str, Any]]
    update_cadence_cdf: Dict[str, Any]
    html_fingerprints: List[Dict[str, Any]]
    source_fingerprint_quality: List[Dict[str, Any]]
    extension_prevalence: List[Dict[str, Any]]
    errors: List[Tuple[str, int]]
    sites_with_feeds_found: int


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
        extension_prevalence=context.extension_prevalence,
        feed_link_signals=context.feed_link_signals,
        update_cadence_cdf=json.dumps(context.update_cadence_cdf),
        errors=context.errors,
        discovery_per_page_hist=discovery.per_page_hist,
        discovery_per_site_hist=discovery.per_site_hist,
        stacked_page_json=json.dumps(discovery.stacked_page),
        site_links_json=json.dumps(discovery.site_chart),
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
        total_pages_f=format_number(report_stats["responses_processed"]),
        pages_with_auto_f=format_number(
            stats.discovery_pages_count
            if stats.discovery_pages_count > 0
            else len(stats.autodiscovery_links)
        ),
        zero_pages_f=format_number(discovery.zero_pages),
        total_sites_f=format_number(discovery.total_sites),
        sites_with_feeds_f=format_number(context.sites_with_feeds_found),
        sites_with_auto_f=format_number(discovery.sites_with_discovery),
        zero_sites_f=format_number(discovery.zero_sites),
        pages_with_duplicates=discovery.pages_with_duplicates,
        duplicate_prevalence_pct=discovery.duplicate_prevalence_pct,
        multi_feed_pages_total=discovery.multi_feed_pages_total,
        duplicate_format_pairs=discovery.duplicate_format_pairs,
    )


def render_report_markdown(context: ReportContext) -> str:
    stats = build_report_stats(context)
    total_parsed = stats["parsed_feeds"]
    quality_split_label = "High-quality feeds"
    quality_prevalence_label = (
        f"Among {format_number(stats['quality_split_count'])} high-quality feeds"
    )
    lines = [
        f"# Web Feed Survey: {context.crawl_id}",
        "",
    ]
    if stats["run_limit"]:
        lines.extend([f"**Limited test run:** LIMIT={stats['run_limit']}", ""])
    if stats["is_opml"]:
        lines.extend(
            [
                "Percentages describe this OPML feed-list report, not the entire Web. "
                "The report reflects the feeds listed in the OPML file, plus any "
                "HTML autodiscovery checks from outline `url` or `htmlUrl` values.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Percentages describe this Common Crawl result set, not the entire Web. "
                "Common Crawl reflects what its crawler fetched, what sites allowed, and "
                "the response-type prefilter and Tranco list/sample limits for this run. "
                "Site counts and TOP_N scoping use the Tranco "
                f"{stats['tranco_list_label']} list, normalized to registrable sites with the "
                "Public Suffix List, including private suffixes for hosted sub-sites.",
                "",
            ]
        )
    lines.extend(
        [
            "## Method Notes",
            "",
            _markdown_table(
                ["Term", "Meaning"],
                [
                    [
                        "Feed URLs checked",
                        "Every URL that the pipeline treated as a feed candidate and "
                        "attempted to fetch or parse.",
                    ],
                    [
                        "Successfully parsed feeds",
                        "RSS/Atom responses that parsed without error. JSON Feed is "
                        "not counted as a feed format in this report.",
                    ],
                    [
                        "Feeds within freshness cutoff",
                        "Parsed feeds with a usable newest-entry date or feed-level "
                        f"updated date within {stats['inactive_quality']['cutoff_days']} days.",
                    ],
                    [
                        "Freshness age",
                        "Computed relative to the response time for the crawl or fetch "
                        "record, falling back to report generation time only if that "
                        "timestamp is unavailable.",
                    ],
                    [
                        quality_split_label,
                        "Parsed feeds with operational quality "
                        f"> {QUALITY_SPLIT_THRESHOLD:.1f}. This is not an editorial "
                        "score; it separates feeds that look recent and usable from "
                        "abandoned, sparse, or low-metadata feeds while keeping both "
                        "groups visible. Severe repeated/default-looking entry metadata "
                        "can cap the score.",
                    ],
                ],
            ),
            "",
            "## Run Summary",
            "",
            "Parse percentages use feed URLs checked as the denominator.",
            "",
            _markdown_table(
                ["Metric", "Value"],
                [
                    [
                        "Responses processed",
                        format_number(stats["responses_processed"]),
                    ],
                    [
                        "Responses analyzed further",
                        format_number(stats["pages_seen"]),
                    ],
                    ["HTML pages processed", format_number(stats["html_responses"])],
                    ["Unique analyzed sites", format_number(stats["sites_seen"])],
                    ["Feed URLs checked", format_number(stats["feed_results_count"])],
                    [
                        "Sniffed feeds",
                        (
                            f"{format_number(stats['feeds_sniffed'])} "
                            f"(RSS {format_number(stats['sniffed_format_counts']['rss'])}; "
                            f"Atom {format_number(stats['sniffed_format_counts']['atom'])})"
                        ),
                    ],
                    ["Successfully parsed feeds", format_number(total_parsed)],
                    [
                        "Broken/unparseable checks",
                        format_number(stats["unparsed_feeds"]),
                    ],
                    ["Parse success rate", f"{stats['parse_success_pct']:.1f}%"],
                ],
            ),
            "",
            "## Autodiscovery",
            "",
            "Autodiscovery coverage and link relation usage. Link relation counts "
            "include only HTML `<link>` elements with an RSS, Atom, or RDF feed "
            "XML media type; unrelated uses of `rel=alternate` are not counted. "
            "Parenthetical page percentages use HTML pages processed as the "
            "denominator. Site percentages use unique analyzed registrable sites.",
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
                        "Feed rel=alternate pages",
                        format_number(stats["discovery_rel_alternate"]),
                    ],
                    [
                        "Feed rel=feed pages",
                        format_number(stats["discovery_rel_feed"]),
                    ],
                    [
                        "Pages using both relations",
                        format_number(stats["discovery_rel_both_page"]),
                    ],
                    [
                        "Pages with a multi-rel link",
                        _format_optional_count(
                            stats["discovery_link_rel_both_page_known"],
                            stats["discovery_link_rel_both_page"],
                        ),
                    ],
                    [
                        "Multi-rel links",
                        format_number(stats["discovery_link_rel_both"]),
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
            "### Duplicate Feed Format Pairs",
            "",
            (
                _markdown_table(
                    ["Coincident formats", "Pages"],
                    [
                        [pair, format_number(count)]
                        for pair, count in context.discovery.duplicate_format_pairs
                    ],
                )
                if context.discovery.duplicate_format_pairs
                else "No duplicate feed format pairs were found in the retained sample."
            ),
            "",
            "### Autodiscovery Usage by HTML Platform",
            "",
            "Rows show known, conservatively detected platform hints in analyzed "
            "HTML responses. The unknown row means no recognized page-side "
            "fingerprint. Parenthetical percentages use HTML pages in that row "
            "as the denominator.",
            "",
            _markdown_table(
                ["Fingerprint", "HTML pages", "Pages with autodiscovery"],
                [
                    [
                        row["fingerprint"],
                        format_number(row["html_pages"]),
                        f"{format_number(row['autodiscovery_pages'])} "
                        f"({row['autodiscovery_pct']:.1f}%)",
                    ]
                    for row in context.html_fingerprints
                ],
            ),
            "",
            "## Feed Availability and Freshness",
            "",
            "Sites with feeds found counts unique registrable sites that host at "
            "least one successfully parsed feed URL.",
            "",
            _markdown_table(
                ["Stage", "Count", "Share"],
                [
                    [
                        "Sites with feeds found",
                        format_number(stats["sites_with_feeds_found"]),
                        (
                            _pct(
                                stats["sites_with_feeds_found"],
                                stats["sites_seen"],
                                2,
                            )
                            + " of analyzed sites"
                        ),
                    ],
                    [
                        "Feed URLs checked",
                        format_number(stats["feed_results_count"]),
                        "100.0% of feed URLs checked",
                    ],
                    [
                        "Parsed RSS/Atom",
                        format_number(stats["parsed_feeds"]),
                        (
                            _pct(stats["parsed_feeds"], stats["feed_results_count"])
                            + " of feed URLs checked"
                        ),
                    ],
                    [
                        "Freshness signal within cutoff",
                        format_number(stats["active_quality"]["n"]),
                        (
                            _pct(
                                stats["active_quality"]["n"],
                                stats["feed_results_count"],
                            )
                            + " of feed URLs checked"
                        ),
                    ],
                    [
                        "Active with entries",
                        format_number(stats["active_quality"]["with_entries"]),
                        (
                            _pct(
                                stats["active_quality"]["with_entries"],
                                stats["feed_results_count"],
                            )
                            + " of feed URLs checked"
                        ),
                    ],
                ],
            ),
            "",
            "## Formats and Quality",
            "",
            f"RSS-family feeds: {format_number(stats['rss_count'])}. "
            f"Atom feeds: {format_number(stats['atom_count'])}. "
            "Denominator: successfully parsed feeds. Parenthetical quality "
            "percentages in the format table use feeds in that format as the "
            "denominator. The quality split is an "
            f"operational filter: feeds with score > {QUALITY_SPLIT_THRESHOLD:.1f} "
            "have a usable freshness signal and enough basic entry/feed metadata to look "
            "usable, while lower-scoring feeds remain included in the all-feeds "
            "columns so abandoned or sparse feeds still affect the totals.",
            "",
            _markdown_table(
                ["Metric", "Value"],
                [
                    [
                        "Mean operational quality, 0-1 score",
                        f"{stats['mean_quality']:.3f}",
                    ],
                    [
                        "Mean among feeds within freshness cutoff",
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
                        "Feeds with default entry titles",
                        format_number(stats["feeds_with_default_entry_titles"]),
                    ],
                    [
                        "Feeds with repeated entry links",
                        format_number(stats["feeds_with_repeated_entry_links"]),
                    ],
                ],
            ),
            "",
            "Quality percentages in the format table use feeds in that format "
            "as the denominator.",
            "",
            _markdown_table(
                [
                    "Format",
                    "Count",
                    f"Quality > {QUALITY_SPLIT_THRESHOLD:.1f}",
                    "Mean quality",
                ],
                [
                    [
                        row["fmt"],
                        format_number(row["count"]),
                        _quality_fraction(row),
                        f"{row['mean']:.3f}",
                    ]
                    for row in context.quality["format_rows"][:20]
                ],
            ),
            "",
            "## Extensions",
            "",
            "Parenthetical percentages in the all-feeds column use successfully "
            "parsed feeds as the denominator. The quality column shows prevalence "
            f"among {format_number(stats['quality_split_count'])} high-quality feeds.",
            "",
            _markdown_table(
                [
                    "Extension",
                    "All parsed feeds",
                    quality_prevalence_label,
                ],
                [
                    [
                        _markdown_extension(row),
                        f"{format_number(row['all_count'])} ({row['all_pct']:.1f}%)",
                        _quality_count_pct(row),
                    ]
                    for row in context.extension_prevalence[:20]
                ],
            ),
            "",
            "## Feed History and Syndication Signals",
            "",
            "Update cadence is inferred from the span between oldest and newest "
            "entry dates divided by entry count, when a feed has at least two "
            "dated entries. Percentages use feeds with an inferred cadence as "
            "the denominator.",
            "",
            _markdown_table(
                ["Inferred cadence within", "Feeds"],
                [
                    [label, f"{pct:.1f}%"]
                    for label, pct in zip(
                        context.update_cadence_cdf.get("labels", []),
                        context.update_cadence_cdf.get("data", []),
                    )
                ],
            ),
            "",
            f"{format_number(context.update_cadence_cdf.get('no_cadence', 0))} "
            "feeds lack enough dated entries to infer cadence.",
            "",
            "Feed link relation signals are taken from feed-level Atom links, "
            "including Atom links embedded in RSS channels. Self/canonical means "
            "rel=self; hub means WebSub/PubSubHubbub discovery; paging/archive "
            "cover RFC-style feed paging and archived-feed links.",
            "",
            _markdown_table(
                ["Signal", "All parsed feeds", quality_prevalence_label],
                [
                    [
                        row["signal"],
                        f"{format_number(row['all_count'])} ({row['all_pct']:.1f}%)",
                        _quality_count_pct(row),
                    ]
                    for row in context.feed_link_signals
                ],
            ),
            "",
            "## Platform Fingerprints",
            "",
            "Rows count known feed generators or platform headers on parsed feeds. "
            "Missing fingerprints mean not identified. Parenthetical percentages "
            "in the all-feeds column use successfully parsed feeds as the "
            "denominator. The quality column shows prevalence among "
            f"{format_number(stats['quality_split_count'])} high-quality feeds. "
            "The final column shows the share of feeds in that fingerprint row "
            "that clear the quality threshold.",
            "",
            _markdown_table(
                [
                    "Fingerprint",
                    "All parsed feeds",
                    quality_prevalence_label,
                    "Quality within fingerprint",
                ],
                [
                    [
                        row["fingerprint"],
                        f"{format_number(row['all_count'])} ({row['all_pct']:.1f}%)",
                        _quality_count_pct(row),
                        f"{row['within_label_quality_pct']:.1f}%",
                    ]
                    for row in context.fingerprint_prevalence
                ],
            ),
            "",
            "### Autodiscovered Feed Quality by Source Platform",
            "",
            "Quality of successfully parsed feeds found through HTML autodiscovery, "
            "grouped by recognized platform hints on the source page. The unknown "
            "row covers autodiscovered feeds whose source page had no recognized "
            "platform fingerprint. Parenthetical percentages use parsed feeds in "
            "that source-platform row as the denominator.",
            "",
            _src_quality_markdown(
                context.source_fingerprint_quality,
                QUALITY_SPLIT_THRESHOLD,
            ),
            "",
            "## Entry Content Profiles",
            "",
            "Parenthetical percentages in the all-feeds column use successfully "
            "parsed feeds as the denominator. The quality column shows prevalence "
            f"among {format_number(stats['quality_split_count'])} high-quality feeds.",
            "",
            _markdown_table(
                ["Profile", "All parsed feeds", quality_prevalence_label],
                [
                    [
                        row["profile"],
                        f"{format_number(row['all_count'])} ({row['all_pct']:.1f}%)",
                        _quality_count_pct(row),
                    ]
                    for row in context.content_profile_prevalence
                ],
            ),
            "",
            "## Languages",
            "",
            "Language-signal counts use successfully parsed feeds as the "
            "denominator. Categories can overlap except the no-language row. "
            "Multiple entry languages means entries expose more than one "
            "language directly, or entry languages differ from the feed/HTTP "
            "language inherited by otherwise untagged entries.",
            "",
            _markdown_table(
                ["Metric", "Feeds"],
                [
                    [
                        "No language information",
                        _count_pct(stats["lang_no_info"], total_parsed),
                    ],
                    [
                        "HTTP Content-Language",
                        _count_pct(stats["lang_src_http"], total_parsed),
                    ],
                    [
                        "Feed-level language",
                        _count_pct(stats["lang_src_feed"], total_parsed),
                    ],
                    [
                        "Entry-level language",
                        _count_pct(stats["lang_src_entry"], total_parsed),
                    ],
                    [
                        "Both HTTP and feed-level language",
                        _count_pct(stats["lang_http_feed"], total_parsed),
                    ],
                    [
                        "Mismatching HTTP and feed-level language",
                        _count_pct(stats["lang_mismatches"], total_parsed),
                    ],
                    [
                        "Multiple entry languages",
                        _count_pct(
                            stats["lang_multiple_entry_languages"], total_parsed
                        ),
                    ],
                    [
                        "Uses hreflang",
                        _count_pct(stats["lang_hreflang"], total_parsed),
                    ],
                ],
            ),
            "",
            _markdown_table(
                ["Language", "All parsed feeds", quality_prevalence_label],
                [
                    [
                        row["language"],
                        f"{format_number(row['all_count'])} ({row['all_pct']:.1f}%)",
                        _quality_count_pct(row),
                    ]
                    for row in context.language_prevalence
                ],
            ),
            "",
            "## Parse Errors",
            "",
            "Error percentages, where shown in the HTML report, use total parse "
            "errors as the denominator.",
            "",
            _markdown_table(
                ["Error", "Count", "Error", "Count"],
                _paired_error_rows(context.errors),
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _paired_error_rows(errors: List[Tuple[str, int]]) -> List[List[str]]:
    rows: List[List[str]] = []
    limited_errors = errors[:20]
    split_idx = (len(limited_errors) + 1) // 2
    left_errors = limited_errors[:split_idx]
    right_errors = limited_errors[split_idx:]
    for idx, (first_error, first_count) in enumerate(left_errors):
        row = [first_error, format_number(first_count)]
        if idx < len(right_errors):
            second_error, second_count = right_errors[idx]
            row.extend([second_error, format_number(second_count)])
        else:
            row.extend(["", ""])
        rows.append(row)
    return rows


def _markdown_extension(row: Dict[str, Any]) -> str:
    if row.get("extension_href"):
        prefix = row["extension_prefix"]
        local = row["extension_local"]
        href = row["extension_href"]
        return f"[{prefix}]({href}):{local}"
    return str(row["extension"])


def _src_quality_markdown(
    rows: List[Dict[str, Any]], quality_threshold: float
) -> str:
    if not rows:
        return "No successfully parsed autodiscovered feeds were found in this run."
    return _markdown_table(
        [
            "Source platform",
            "Autodiscovered parsed feeds",
            f"Quality > {quality_threshold:.1f}",
            "Mean quality",
        ],
        [
            [
                row["fingerprint"],
                format_number(row["parsed_feeds"]),
                _quality_fraction(row),
                f"{row['mean_quality']:.3f}",
            ]
            for row in rows
        ],
    )


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
        "is_opml": context.crawl_id.startswith("OPML:"),
        "source_label": (
            "OPML feed list"
            if context.crawl_id.startswith("OPML:")
            else "Common Crawl Archive"
        ),
        "pages_seen": stats.pages_seen,
        "responses_processed": stats.responses_processed or stats.pages_seen,
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
        "sniffed_format_counts": _sniffed_format_counts(stats.feed_results),
        "formats": context.formats,
        "languages": context.languages,
        "language_prevalence": context.language_prevalence,
        "fingerprint_prevalence": context.fingerprint_prevalence,
        "feed_link_signals": context.feed_link_signals,
        "update_cadence_cdf": context.update_cadence_cdf,
        "html_fingerprints": context.html_fingerprints,
        "source_fingerprint_quality": context.source_fingerprint_quality,
        "extension_prevalence": context.extension_prevalence,
        "error_types": context.errors,
        "total_errors": sum(count for _, count in context.errors),
        "error_column_rows": _paired_error_column_rows(context.errors),
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
        "feeds_with_repeated_entry_links": aggregate["feeds_with_repeated_entry_links"],
        "pages_with_autodiscovery": getattr(
            stats, "discovery_pages_count", len(discovery.page_to_feeds)
        ),
        "sites_with_feeds_found": context.sites_with_feeds_found,
        "sites_with_autodiscovery": discovery.sites_with_discovery,
        "top_n": stats.top_n,
        "tranco_include_subdomains": stats.tranco_include_subdomains,
        "tranco_list_label": tranco_list_label(stats.tranco_include_subdomains),
        "run_limit": stats.run_limit,
        "feeds_sniffed": stats.feeds_sniffed,
        "total_entries": aggregate["total_entries"],
        "lang_src_http": aggregate["lang_src_http"],
        "lang_src_feed": aggregate["lang_src_feed"],
        "lang_src_entry": aggregate["lang_src_entry"],
        "lang_mismatches": aggregate["lang_mismatches"],
        "lang_multiple_in_feed": aggregate["lang_multiple_in_feed"],
        "lang_no_info": aggregate["lang_no_info"],
        "lang_http_feed": aggregate["lang_http_feed"],
        "lang_hreflang": aggregate["lang_hreflang"],
        "lang_multiple_entry_languages": aggregate["lang_multiple_entry_languages"],
        **_runtime_counter_stats(stats),
        "discovery_link_rel_both_page_known": (
            bool(stats.discovery_link_rel_both_page)
            or stats.discovery_link_rel_both == 0
        ),
        "content_types_collapsed": context.content_types_collapsed,
        "content_profile_dist": context.content_profile_dist,
        "content_profile_prevalence": context.content_profile_prevalence,
        "lang_count_hist": context.lang_count_hist,
        "quality_hist": quality["hist"],
        "quality_split_threshold": QUALITY_SPLIT_THRESHOLD,
        "quality_split_count": quality["split_count"],
        "mean_quality": round(quality["mean"], 3),
        "active_quality": quality["active"],
        "inactive_quality": quality["inactive"],
    }


def _runtime_counter_stats(stats: Stats) -> Dict[str, int]:
    return {
        name: getattr(stats, name)
        for name in (
            "discovery_rel_alternate",
            "discovery_rel_feed",
            "discovery_rel_both_page",
            "discovery_multi_rel_url",
            "discovery_link_rel_both",
            "discovery_link_rel_both_page",
        )
    }


def _format_optional_count(known: bool, value: int) -> str:
    return format_number(value) if known else "not recorded"


def _sniffed_format_counts(feed_results: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    counts = {"rss": 0, "atom": 0, "other": 0}
    for result in feed_results.values():
        if not result.get("valid") or "sniffed" not in (
            result.get("candidate_sources") or []
        ):
            continue
        feed_format = str(result.get("format") or "").lower()
        if feed_format.startswith("atom"):
            counts["atom"] += 1
        elif feed_format.startswith("rss") or feed_format == "rdf":
            counts["rss"] += 1
        else:
            counts["other"] += 1
    return counts


def _count_pct(count: int, denominator: int) -> str:
    return f"{format_number(count)} ({_pct(count, denominator)})"


def _quality_fraction(row: Dict[str, Any]) -> str:
    return (
        f"{format_number(row['quality_count'])}/"
        f"{format_number(row['quality_denominator'])} "
        f"({row['quality_pct']:.1f}%)"
    )


def _quality_count_pct(row: Dict[str, Any]) -> str:
    return f"{format_number(row['quality_count'])} ({row['quality_pct']:.1f}%)"


def _paired_error_column_rows(errors: List[Tuple[str, int]]) -> List[List[Any]]:
    rows: List[List[Any]] = []
    limited_errors = errors[:20]
    split_idx = (len(limited_errors) + 1) // 2
    left_errors = limited_errors[:split_idx]
    right_errors = limited_errors[split_idx:]
    for idx, (first_error, first_count) in enumerate(left_errors):
        row: List[Any] = [first_error, first_count]
        if idx < len(right_errors):
            second_error, second_count = right_errors[idx]
            row.extend([second_error, second_count])
        else:
            row.extend(["", 0])
        rows.append(row)
    return rows


def _pct(numerator: int, denominator: int, digits: int = 1) -> str:
    if not denominator:
        return f"{0.0:.{digits}f}%"
    return f"{numerator / denominator * 100:.{digits}f}%"


def _markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    escaped_headers = [_escape_markdown_cell(header) for header in headers]
    escaped_rows = [
        [_escape_markdown_cell(cell) for cell in row] for row in rows
    ]
    widths = [
        max(len(escaped_headers[idx]), 3, *(len(row[idx]) for row in escaped_rows))
        for idx in range(len(headers))
    ]
    lines = [
        "| "
        + " | ".join(
            cell.ljust(widths[idx]) for idx, cell in enumerate(escaped_headers)
        )
        + " |",
        "| " + " | ".join("-" * widths[idx] for idx in range(len(headers))) + " |",
    ]
    for row in escaped_rows:
        lines.append(
            "| "
            + " | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row))
            + " |"
        )
    return "\n".join(lines)


def _escape_markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
