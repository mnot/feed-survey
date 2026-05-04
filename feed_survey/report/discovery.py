from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from feed_survey.analysis import Stats
from feed_survey.analysis.feed_helpers import normalize_entry_title
from feed_survey.report.histograms import make_histogram
from feed_survey.url import normalize_url_for_grouping


@dataclass(frozen=True)
class DiscoverySummary:
    page_to_feeds: Dict[str, Set[str]]
    site_to_feeds: Dict[str, Set[str]]
    per_page_hist: Dict[str, int]
    per_site_hist: Dict[str, int]
    total_sites: int
    zero_pages: int
    zero_sites: int
    stacked_page: Dict[str, Any]
    stacked_site: Dict[str, Any]
    pages_with_duplicates: int
    duplicate_prevalence_pct: float
    multi_feed_pages_total: int
    duplicate_format_pairs: List[Tuple[str, int]]


def build_discovery_summary(stats: Stats) -> DiscoverySummary:
    page_to_feeds = build_page_map(stats)
    site_to_feeds = build_site_map(stats)

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
    zero_sites = max(0, total_sites - len(site_to_feeds))
    discovery_site_counts = [len(feeds) for feeds in site_to_feeds.values()]
    per_site_hist = make_histogram(discovery_site_counts, bins="discovery")
    per_site_hist.pop("0", None)

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
    stacked_site = build_stacked_data(stats, site_to_feeds, zero_sites)
    _remove_zero_bucket(stacked_site)

    return DiscoverySummary(
        page_to_feeds=page_to_feeds,
        site_to_feeds=site_to_feeds,
        per_page_hist=per_page_hist,
        per_site_hist=per_site_hist,
        total_sites=total_sites,
        zero_pages=zero_pages,
        zero_sites=zero_sites,
        stacked_page=stacked_page,
        stacked_site=stacked_site,
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


def build_stacked_data(
    stats: Stats, mapping: Dict[str, Set[str]], zero_count: int
) -> Dict[str, Any]:
    labels = [str(i) for i in range(11)] + [
        "11-15",
        "16-20",
        "21-50",
        "51-100",
        "100+",
    ]
    thresholds: List[Union[int, float]] = list(range(11)) + [
        16,
        21,
        51,
        101,
        float("inf"),
    ]
    stacked: Dict[str, Any] = {
        "labels": labels,
        "has_entries": [0] * len(labels),
        "valid_only": [0] * len(labels),
        "success_only": [0] * len(labels),
        "other": [0] * len(labels),
    }
    stacked["other"][0] = zero_count

    for feeds in mapping.values():
        count = len(feeds)
        bin_idx = -1
        for idx, threshold in enumerate(thresholds):
            if idx < 11:
                if count == threshold:
                    bin_idx = idx
                    break
            elif count < threshold:
                bin_idx = idx
                break
        if bin_idx == -1:
            continue

        has_entries = False
        valid_only = False
        success_only = False
        for feed_url in feeds:
            res = stats.feed_results.get(feed_url, {})
            if res.get("entries_count", 0) > 0:
                has_entries = True
                break
            if res.get("valid"):
                valid_only = True
            elif res.get("status", 0) < 400 and res.get("status", 0) > 0:
                success_only = True

        if has_entries:
            stacked["has_entries"][bin_idx] += 1
        elif valid_only:
            stacked["valid_only"][bin_idx] += 1
        elif success_only:
            stacked["success_only"][bin_idx] += 1
        else:
            stacked["other"][bin_idx] += 1
    return stacked


def _remove_zero_bucket(stacked: Dict[str, Any]) -> None:
    if "0" not in stacked["labels"]:
        return
    idx = stacked["labels"].index("0")
    stacked["labels"].pop(idx)
    stacked["has_entries"].pop(idx)
    stacked["valid_only"].pop(idx)
    stacked["success_only"].pop(idx)
    stacked["other"].pop(idx)
