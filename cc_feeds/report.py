import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Union, cast

from jinja2 import Environment, FileSystemLoader

from .processor import Stats
from .utils import get_domain


def format_number(value: Union[int, float]) -> str:
    return f"{value:,}"


def make_histogram(
    data: Union[Sequence[Any], Dict[Any, int]],
    bins: Optional[str] = None,
    log_scale: bool = False,
) -> Dict[str, int]:
    if not data:
        return {}

    if isinstance(data, dict):
        counts = data
    else:
        counts = {}
        for item in data:
            counts[item] = counts.get(item, 0) + 1

    if not counts:
        return {}

    if log_scale:
        # Log-like buckets for content length
        labels = [
            "0-100",
            "100-500",
            "500-1k",
            "1k-5k",
            "5k-10k",
            "10k-50k",
            "50k-100k",
            "100k-500k",
            "500k+",
        ]
        thresholds = [100, 500, 1000, 5000, 10000, 50000, 100000, 500000, float("inf")]
        hist = {label: 0 for label in labels}
        for val, count in counts.items():
            for i, threshold in enumerate(thresholds):
                if val < threshold:
                    hist[labels[i]] += count
                    break
        return hist

    if bins == "discovery":
        # 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11-15, 16-20, 21-50, 51-100, 100+
        labels = [str(i) for i in range(11)] + [
            "11-15",
            "16-20",
            "21-50",
            "51-100",
            "100+",
        ]
        hist = {label: 0 for label in labels}
        for val, count in counts.items():
            if val <= 10:
                hist[str(val)] += count
            elif val <= 15:
                hist["11-15"] += count
            elif val <= 20:
                hist["16-20"] += count
            elif val <= 50:
                hist["21-50"] += count
            elif val <= 100:
                hist["51-100"] += count
            else:
                hist["100+"] += count
        return hist

    if bins == "entries":
        # High granularity for lower end
        labels = [
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "10",
            "11-15",
            "16-20",
            "21-30",
            "31-50",
            "51-100",
            "100+",
        ]
        hist = {label: 0 for label in labels}
        for val, count in counts.items():
            if val == 0:
                hist["0"] += count
            elif val == 1:
                hist["1"] += count
            elif val == 2:
                hist["2"] += count
            elif val == 3:
                hist["3"] += count
            elif val == 4:
                hist["4"] += count
            elif val == 5:
                hist["5"] += count
            elif val == 6:
                hist["6"] += count
            elif val == 7:
                hist["7"] += count
            elif val == 8:
                hist["8"] += count
            elif val == 9:
                hist["9"] += count
            elif val == 10:
                hist["10"] += count
            elif val <= 15:
                hist["11-15"] += count
            elif val <= 20:
                hist["16-20"] += count
            elif val <= 30:
                hist["21-30"] += count
            elif val <= 50:
                hist["31-50"] += count
            elif val <= 100:
                hist["51-100"] += count
            else:
                hist["100+"] += count
        return hist

    # Default simple histogram
    max_val = max(counts.keys())
    if max_val == 0:
        return {"0": sum(counts.values())}
    bin_size = max(1, max_val // 10)
    hist = {}
    for val, count in counts.items():
        bin_idx = val // bin_size
        label = f"{bin_idx*bin_size}-{(bin_idx+1)*bin_size-1}"
        hist[label] = hist.get(label, 0) + count
    return dict(sorted(hist.items(), key=lambda item: int(item[0].split("-")[0])))


def generate_report(stats: Stats, crawl_id: str, output_path: str) -> None:
    # Discovery Histograms (including 0)
    # ONLY reflect feeds found by autodiscovery
    discovered_urls = set(stats.autodiscovery_links.keys())
    discovered_results = {
        url: res for url, res in stats.feed_results.items() if url in discovered_urls
    }

    # Aggregate Data
    agg = _aggregate_feed_data(discovered_results)

    # --- Discovery Mapping ---
    page_to_feeds = _build_page_map(stats)
    site_to_feeds = _build_site_map(stats)

    discovery_page_counts = [len(f) for f in page_to_feeds.values()]
    zero_pages = stats.pages_seen - len(page_to_feeds)
    discovery_page_counts.extend([0] * zero_pages)
    discovery_per_page_hist = make_histogram(discovery_page_counts, bins="discovery")

    discovery_site_counts = [len(f) for f in site_to_feeds.values()]
    zero_sites = len(stats.sites_seen) - len(site_to_feeds)
    discovery_site_counts.extend([0] * zero_sites)
    discovery_per_site_hist = make_histogram(discovery_site_counts, bins="discovery")

    # Stacked discovery data
    stacked = _build_stacked_data(stats, page_to_feeds, zero_pages)

    # Prep Histograms
    content_length_hist = make_histogram(agg["content_lengths"], log_scale=True)
    entry_counts_hist = make_histogram(agg["entry_counts"], bins="entries")
    # Recency histograms
    now = stats.max_crawl_time or datetime.now(timezone.utc)
    recency_labels = _get_recency_labels(now)
    feed_recency_hist = _build_recency_histogram(
        discovered_results, "updated_date", now, recency_labels
    )
    entry_recency_hist = _build_recency_histogram(
        discovered_results, "newest_entry_date", now, recency_labels
    )

    # Sort data
    formats = sorted(agg["formats"].items(), key=lambda item: item[1], reverse=True)
    languages = sorted(agg["languages"].items(), key=lambda item: item[1], reverse=True)
    extensions = sorted(
        agg["extensions"].items(), key=lambda item: item[1], reverse=True
    )
    errors = sorted(stats.error_types.items(), key=lambda item: item[1], reverse=True)

    # Prep data for template
    report_stats = {
        "pages_seen": stats.pages_seen,
        "sites_seen": stats.sites_seen,
        "feed_results": discovered_results,
        "formats": formats,
        "languages": languages,
        "extensions": extensions,
        "error_types": errors,
        "feeds_with_content": agg["feeds_with_content"],
        "feeds_with_summary": agg["feeds_with_summary"],
        "feeds_with_neither": agg["feeds_with_neither"],
        "last_updated_dates": agg["last_updated_dates"],
        "pages_with_autodiscovery": len(page_to_feeds),
        "sites_with_autodiscovery": len(site_to_feeds),
        "top_n": stats.top_n,
    }

    env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
    env.filters["comma"] = format_number
    template = env.get_template("report_template.html")

    html = template.render(
        stats=report_stats,
        crawl_id=crawl_id,
        formats=formats,
        languages=languages,
        extensions=extensions,
        errors=errors,
        discovery_per_page_hist=discovery_per_page_hist,
        discovery_per_site_hist=discovery_per_site_hist,
        stacked_discovery_json=json.dumps(stacked),
        content_length_hist=content_length_hist,
        entry_counts_hist=entry_counts_hist,
        feed_recency_hist=feed_recency_hist,
        entry_recency_hist=entry_recency_hist,
        total_pages_f=format_number(stats.pages_seen),
        pages_with_auto_f=format_number(len(page_to_feeds)),
        total_sites_f=format_number(len(stats.sites_seen)),
        sites_with_auto_f=format_number(len(site_to_feeds)),
    )

    with open(output_path, "w", encoding="utf-8") as f_out:
        f_out.write(html)


def _aggregate_feed_data(results: Dict[str, Any]) -> Dict[str, Any]:
    formats: Dict[str, int] = {}
    languages: Dict[str, int] = {}
    extensions: Dict[str, int] = {}
    entry_counts: List[int] = []
    content_lengths: List[int] = []
    last_updated_dates: List[Any] = []
    feeds_with_content: int = 0
    feeds_with_summary: int = 0
    feeds_with_neither: int = 0

    for res in results.values():
        res = cast(Dict[str, Any], res)
        if not res.get("valid"):
            continue

        fmt = res.get("format") or "unknown"
        formats[fmt] = formats.get(fmt, 0) + 1

        if res.get("languages"):
            for lang in res["languages"]:
                languages[lang] = languages.get(lang, 0) + 1
        else:
            languages["unknown"] = languages.get("unknown", 0) + 1

        if res.get("has_content"):
            feeds_with_content += 1
        elif res.get("has_summary"):
            feeds_with_summary += 1
        else:
            feeds_with_neither += 1

        entry_counts.append(res.get("entries_count", 0))
        content_lengths.extend(res.get("content_lengths", []))

        for ext in res.get("extensions", []):
            extensions[ext] = extensions.get(ext, 0) + 1

        if res.get("updated_date"):
            last_updated_dates.append(res["updated_date"])

    return {
        "formats": formats,
        "languages": languages,
        "extensions": extensions,
        "entry_counts": entry_counts,
        "content_lengths": content_lengths,
        "last_updated_dates": last_updated_dates,
        "feeds_with_content": feeds_with_content,
        "feeds_with_summary": feeds_with_summary,
        "feeds_with_neither": feeds_with_neither,
    }


def _build_page_map(stats: Stats) -> Dict[str, List[str]]:
    page_to_feeds: Dict[str, List[str]] = {}
    for feed_url, pages in stats.autodiscovery_links.items():
        for page_url in pages:
            if page_url not in page_to_feeds:
                page_to_feeds[page_url] = []
            page_to_feeds[page_url].append(feed_url)
    return page_to_feeds


def _build_site_map(stats: Stats) -> Dict[str, Set[str]]:
    site_to_feeds: Dict[str, Set[str]] = {}
    for feed_url, pages in stats.autodiscovery_links.items():
        for page_url in pages:
            domain = get_domain(page_url)
            if domain not in site_to_feeds:
                site_to_feeds[domain] = set()
            site_to_feeds[domain].add(feed_url)
    return site_to_feeds


def _build_stacked_data(
    stats: Stats, page_map: Dict[str, List[str]], zero_pages: int
) -> Dict[str, Any]:
    labels = [str(i) for i in range(11)] + [
        "11-15",
        "16-20",
        "21-50",
        "51-100",
        "100+",
    ]
    thresholds = list(range(11)) + [16, 21, 51, 101, float("inf")]
    stacked: Dict[str, Any] = {
        "labels": labels,
        "has_entries": [0] * len(labels),
        "valid_only": [0] * len(labels),
        "success_only": [0] * len(labels),
        "other": [0] * len(labels),
    }
    stacked["other"][0] = zero_pages

    for feeds in page_map.values():
        count = len(feeds)
        bin_idx = -1
        for i, threshold in enumerate(thresholds):
            if i < 11:
                if count == threshold:
                    bin_idx = i
                    break
            elif count < threshold:
                bin_idx = i
                break
        if bin_idx != -1:
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


def _get_recency_labels(_now: datetime) -> List[str]:
    return [
        "Today",
        "Yesterday",
        "2 days ago",
        "3 days ago",
        "4 days ago",
        "5 days ago",
        "6 days ago",
        "Last week",
        "Last month",
        "Last year",
        "Older",
        "Unknown",
    ]


def _build_recency_histogram(
    results: Dict[str, Any], key: str, now: datetime, labels: List[str]
) -> Dict[str, int]:
    hist = {label: 0 for label in labels}
    for info in results.values():
        val = info.get(key)
        if not val:
            hist["Unknown"] += 1
            continue
        try:
            dt = datetime(
                val[0], val[1], val[2], val[3], val[4], val[5], tzinfo=timezone.utc
            )
            delta = now - dt
            days = delta.days
            if days < 0:
                hist["Today"] += 1  # Future is today for this purpose
            elif days == 0:
                hist["Today"] += 1
            elif days == 1:
                hist["Yesterday"] += 1
            elif days < 7:
                hist[f"{days} days ago"] += 1
            elif days < 14:
                hist["Last week"] += 1
            elif days < 31:
                hist["Last month"] += 1
            elif days < 365:
                hist["Last year"] += 1
            else:
                hist["Older"] += 1
        except (ValueError, TypeError, IndexError):
            hist["Unknown"] += 1
    return hist
