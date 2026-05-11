from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, List, Optional, Set, Tuple

from feed_survey.analysis import Stats
from feed_survey.analysis.feed_helpers import normalize_entry_title
from feed_survey.report.histograms import make_histogram
from feed_survey.url import normalize_url_for_grouping


@dataclass(frozen=True)
class DiscoverySummary:
    page_to_feeds: Dict[str, Set[str]]
    per_page_hist: Dict[str, int]
    per_site_hist: Dict[str, int]
    total_sites: int
    zero_pages: int
    zero_sites: int
    sites_with_discovery: int
    site_names: Set[str]
    stacked_page: Dict[str, Any]
    site_chart: Dict[str, Any]
    pages_with_duplicates: int
    duplicate_prevalence_pct: float
    multi_feed_pages_total: int
    duplicate_format_pairs: List[Tuple[str, int]]


def build_discovery_summary(stats: Stats) -> DiscoverySummary:
    page_to_feeds = build_page_map(stats)

    total_pages = _html_response_count(stats) or stats.pages_seen
    pages_with_discovery = getattr(stats, "discovery_pages_count", 0) or len(
        page_to_feeds
    )
    zero_pages = max(0, total_pages - pages_with_discovery)
    page_count_hist = getattr(stats, "discovery_links_per_page_counts", {})
    if page_count_hist:
        per_page_hist = make_histogram(page_count_hist, bins="discovery")
    else:
        discovery_page_counts = [len(feeds) for feeds in page_to_feeds.values()]
        per_page_hist = make_histogram(discovery_page_counts, bins="discovery")
    per_page_hist.pop("0", None)

    total_sites = getattr(stats, "sites_seen_count", len(stats.sites_seen))
    site_count_hist = getattr(stats, "discovery_feeds_per_site_counts", {})
    if site_count_hist:
        per_site_hist = make_histogram(site_count_hist, bins="discovery")
        sites_with_discovery = sum(site_count_hist.values())
        site_names = set(getattr(stats, "site_discovered_feeds", {}))
    else:
        site_to_feeds = build_site_map(stats)
        site_counts = [len(feeds) for feeds in site_to_feeds.values()]
        per_site_hist = make_histogram(site_counts, bins="discovery")
        sites_with_discovery = len(site_to_feeds)
        site_names = set(site_to_feeds)
    per_site_hist.pop("0", None)
    zero_sites = max(0, total_sites - sites_with_discovery)

    duplicate_counts = detect_duplicates(stats.multi_feed_pages, stats.feed_results)
    duplicate_format_pairs = detect_duplicate_format_pairs(
        stats.multi_feed_pages, stats.feed_results
    )
    pages_with_duplicates = len(duplicate_counts)
    multi_feed_pages_total = len(stats.multi_feed_pages)
    duplicate_prevalence_pct = (
        round(pages_with_duplicates / multi_feed_pages_total * 100, 1)
        if multi_feed_pages_total
        else 0.0
    )

    stacked_page = build_page_chart_data(per_page_hist)
    site_chart = build_page_chart_data(per_site_hist)

    return DiscoverySummary(
        page_to_feeds=page_to_feeds,
        per_page_hist=per_page_hist,
        per_site_hist=per_site_hist,
        total_sites=total_sites,
        zero_pages=zero_pages,
        zero_sites=zero_sites,
        sites_with_discovery=sites_with_discovery,
        site_names=site_names,
        stacked_page=stacked_page,
        site_chart=site_chart,
        pages_with_duplicates=pages_with_duplicates,
        duplicate_prevalence_pct=duplicate_prevalence_pct,
        multi_feed_pages_total=multi_feed_pages_total,
        duplicate_format_pairs=duplicate_format_pairs,
    )


def build_page_map(stats: Stats) -> Dict[str, Set[str]]:
    page_to_feeds: Dict[str, Set[str]] = {}
    for feed_url, pages_or_sites in stats.autodiscovery_links.items():
        for page_or_site in pages_or_sites:
            if page_or_site not in page_to_feeds:
                page_to_feeds[page_or_site] = set()
            page_to_feeds[page_or_site].add(feed_url)
    return page_to_feeds


def _html_response_count(stats: Stats) -> int:
    total = 0
    for content_type, count in stats.content_type_counts.items():
        content_type_lower = content_type.lower()
        if (
            "text/html" in content_type_lower
            or "application/xhtml" in content_type_lower
        ):
            total += count
    return total


def build_page_chart_data(per_page_hist: Dict[str, int]) -> Dict[str, Any]:
    non_empty = {label: count for label, count in per_page_hist.items() if count}
    return {
        "labels": list(non_empty.keys()),
        "counts": list(non_empty.values()),
    }


def build_site_map(stats: Stats) -> Dict[str, Set[str]]:
    site_to_feeds: Dict[str, Set[str]] = {}
    for feed_url, sites in stats.autodiscovery_links.items():
        for site in sites:
            if site not in site_to_feeds:
                site_to_feeds[site] = set()
            site_to_feeds[site].add(feed_url)
    return site_to_feeds


def detect_duplicates(
    multi_feed_pages: Dict[str, List[str]], feed_results: Dict[str, Any]
) -> List[int]:
    duplicate_counts = []
    for feed_urls in multi_feed_pages.values():
        page_dups = 0
        for feeds in _duplicate_feed_groups(feed_urls, feed_results):
            page_dups += len(feeds) - 1
        if page_dups > 0:
            duplicate_counts.append(page_dups)
    return duplicate_counts


def detect_duplicate_format_pairs(
    multi_feed_pages: Dict[str, List[str]], feed_results: Dict[str, Any]
) -> List[Tuple[str, int]]:
    pair_counts: Dict[str, int] = {}
    for feed_urls in multi_feed_pages.values():
        for feeds in _duplicate_feed_groups(feed_urls, feed_results):
            formats = sorted(
                str(feed_results.get(feed_url, {}).get("format") or "unknown")
                for feed_url in feeds
            )
            for first, second in combinations(formats, 2):
                pair = f"{first} and {second}"
                pair_counts[pair] = pair_counts.get(pair, 0) + 1

    pairs = sorted(pair_counts.items(), key=lambda item: item[1], reverse=True)
    return pairs[:10]


def _duplicate_feed_groups(
    feed_urls: List[str], feed_results: Dict[str, Any]
) -> List[Set[str]]:
    link_to_feeds: Dict[Tuple[Optional[str], Optional[str]], Set[str]] = {}
    for url in feed_urls:
        res = feed_results.get(url)
        if not isinstance(res, dict):
            continue
        link = res.get("link")
        title = res.get("title")
        if link or title:
            key = (
                normalize_url_for_grouping(link) if link else None,
                normalize_entry_title(title),
            )
            if key not in link_to_feeds:
                link_to_feeds[key] = set()
            link_to_feeds[key].add(url)
    return [feeds for feeds in link_to_feeds.values() if len(feeds) > 1]
