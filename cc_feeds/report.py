import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union, cast

import dateutil.parser
from jinja2 import Environment, FileSystemLoader

try:
    from .processor import Stats
    from .utils import get_domain
except (ImportError, ValueError):
    try:
        from processor import Stats  # type: ignore[import-not-found,no-redef]
        from utils import get_domain  # type: ignore[import-not-found,no-redef]
    except ImportError:
        from cc_feeds.processor import Stats
        from cc_feeds.utils import get_domain


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

    if bins == "natural":
        # 0, -127, -254, -511, -1023, etc.
        labels = ["0", "-127", "-254", "-511", "-1023"]
        nat_thresholds = [0, 127, 254, 511, 1023]

        # Add higher buckets dynamically up to max_val
        max_val = max(counts.keys()) if counts else 0
        curr = 1024
        while curr <= max_val:
            labels.append(f"-{curr*2//1024}k")
            nat_thresholds.append(curr * 2 - 1)
            curr *= 2

        hist = {label: 0 for label in labels}
        for val, count in counts.items():
            if val == 0:
                hist["0"] += count
                continue
            for i, nat_t in enumerate(nat_thresholds):
                if i == 0:
                    continue  # Handled val == 0
                if val <= nat_t:
                    hist[labels[i]] += count
                    break
        return hist

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
        log_thresholds: List[Union[int, float]] = [
            100,
            500,
            1000,
            5000,
            10000,
            50000,
            100000,
            500000,
            float("inf"),
        ]
        hist = {label: 0 for label in labels}
        for val, count in counts.items():
            for i, log_t in enumerate(log_thresholds):
                if val < log_t:
                    hist[labels[i]] += count
                    break
        return hist

    if bins == "discovery":
        # 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, -15, -20, -50, -100, 100+
        labels = (
            ["0"]
            + [str(i) for i in range(1, 11)]
            + [
                "-15",
                "-20",
                "-50",
                "-100",
                "100+",
            ]
        )
        hist = {label: 0 for label in labels}
        for val, count in counts.items():
            if val == 0:
                hist["0"] += count
            elif val <= 10:
                hist[str(val)] += count
            elif val <= 15:
                hist["-15"] += count
            elif val <= 20:
                hist["-20"] += count
            elif val <= 50:
                hist["-50"] += count
            elif val <= 100:
                hist["-100"] += count
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
        low = bin_idx * bin_size
        high = (bin_idx + 1) * bin_size - 1
        if low == high:
            label = str(low)
        else:
            label = f"-{high//1024}k" if high >= 1024 else f"-{high}"
        hist[label] = hist.get(label, 0) + count
    return dict(
        sorted(
            hist.items(),
            key=lambda item: (
                int(item[0].lstrip("-").rstrip("k+")) * 1024
                if "k" in item[0]
                else int(item[0].lstrip("-").rstrip("+"))
            ),
        )
    )


def generate_report(stats: Stats, crawl_id: str, output_path: str) -> None:
    # Discovery Histograms (including 0)
    # ONLY reflect feeds found by autodiscovery
    discovered_urls = set(stats.autodiscovery_links.keys())
    discovered_results = {
        url: res
        for url, res in stats.feed_results.items()
        if url in discovered_urls
        and isinstance(res, dict)
        and res.get("valid")
        and not res.get("error")
    }

    # Inject total discovery count from discovery_domain_counts into result for display
    for url, res in discovered_results.items():
        res["total_discovery_count"] = stats.discovery_domain_counts.get(url, 1)

    # Aggregate Data
    agg = _aggregate_feed_data(discovered_results)

    # --- Discovery Mapping ---
    page_to_feeds = _build_page_map(stats)
    site_to_feeds = _build_site_map(stats)

    discovery_page_counts = [len(f) for f in page_to_feeds.values()]
    total_pages = stats.pages_seen
    zero_pages = max(0, total_pages - len(page_to_feeds))

    discovery_per_page_hist = make_histogram(discovery_page_counts, bins="discovery")
    if "0" in discovery_per_page_hist:
        del discovery_per_page_hist["0"]

    discovery_site_counts = [len(f) for f in site_to_feeds.values()]
    total_sites = getattr(stats, "sites_seen_count", len(stats.sites_seen))
    zero_sites = max(0, total_sites - len(site_to_feeds))

    discovery_per_site_hist = make_histogram(discovery_site_counts, bins="discovery")
    if "0" in discovery_per_site_hist:
        del discovery_per_site_hist["0"]

    # Duplicate detection
    duplicate_counts = _detect_duplicates(stats.multi_feed_pages, stats.feed_results)
    duplicates_per_page_hist = make_histogram(duplicate_counts, bins="discovery")
    if "0" in duplicates_per_page_hist:
        del duplicates_per_page_hist["0"]

    # Stacked discovery data
    stacked_page = _build_stacked_data(stats, page_to_feeds, zero_pages)
    stacked_site = _build_stacked_data(stats, site_to_feeds, zero_sites)

    for s in [stacked_page, stacked_site]:
        if "0" in s["labels"]:
            idx = s["labels"].index("0")
            s["labels"].pop(idx)
            s["has_entries"].pop(idx)
            s["valid_only"].pop(idx)
            s["success_only"].pop(idx)
            s["other"].pop(idx)

    # Prep data for template
    max_crawl_time = None
    if stats.max_crawl_time_str:
        try:
            max_crawl_time = dateutil.parser.parse(stats.max_crawl_time_str)
            if max_crawl_time.tzinfo is None:
                max_crawl_time = max_crawl_time.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Prep Histograms
    content_length_hist = make_histogram(stats.content_length_counts, log_scale=True)
    entry_counts_hist = make_histogram(agg["entry_counts"], bins="entries")
    # Use the parsed max_crawl_time if available, otherwise now
    now = max_crawl_time or datetime.now(timezone.utc)
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
        "max_crawl_time": max_crawl_time,
        "sites_seen": getattr(stats, "sites_seen_count", len(stats.sites_seen)),
        "feed_results_count": len(stats.feed_results),
        "formats": formats,
        "languages": languages,
        "extensions": extensions,
        "error_types": errors,
        "feeds_with_content": agg["feeds_with_content"],
        "feeds_with_summary": agg["feeds_with_summary"],
        "feeds_with_neither": agg["feeds_with_neither"],
        "last_updated_dates": agg["last_updated_dates"],
        "pages_with_autodiscovery": getattr(
            stats, "discovery_pages_count", len(page_to_feeds)
        ),
        "sites_with_autodiscovery": len(site_to_feeds),
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
        "content_types": sorted(
            stats.content_type_counts.items(), key=lambda x: x[1], reverse=True
        ),
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
        stacked_page_json=json.dumps(stacked_page),
        stacked_site_json=json.dumps(stacked_site),
        charsets_per_format=agg["charsets_per_format"],
        content_length_hist=make_histogram(stats.content_length_counts, bins="natural"),
        entry_counts_hist=make_histogram(agg["entry_counts"], bins="entries"),
        feed_recency_hist=feed_recency_hist,
        entry_recency_hist=entry_recency_hist,
        total_pages_f=format_number(stats.pages_seen),
        pages_with_auto_f=format_number(
            stats.discovery_pages_count
            if stats.discovery_pages_count > 0
            else len(stats.autodiscovery_links)
        ),
        zero_pages_f=format_number(zero_pages),
        total_sites_f=format_number(
            getattr(stats, "sites_seen_count", len(stats.sites_seen))
        ),
        sites_with_auto_f=format_number(len(site_to_feeds)),
        zero_sites_f=format_number(zero_sites),
        duplicates_per_page_hist=duplicates_per_page_hist,
    )

    with open(output_path, "w", encoding="utf-8") as f_out:
        f_out.write(html)


def _aggregate_feed_data(results: Dict[str, Any]) -> Dict[str, Any]:
    formats: Dict[str, int] = {}
    languages: Dict[str, int] = {}
    extensions: Dict[Any, int] = {}
    entry_counts: List[int] = []
    last_updated_dates: List[Any] = []
    feeds_with_content: int = 0
    feeds_with_summary: int = 0
    feeds_with_neither: int = 0
    charsets_per_format: Dict[str, Dict[str, int]] = {}

    # Unique stats
    total_entries: int = 0
    lang_src_http: int = 0
    lang_src_feed: int = 0
    lang_src_entry: int = 0
    lang_mismatches: int = 0
    lang_multiple_in_feed: int = 0

    for res in results.values():
        res = cast(Dict[str, Any], res)
        if not res.get("valid"):
            continue

        fmt = res.get("format") or "unknown"
        formats[fmt] = formats.get(fmt, 0) + 1

        # Track charset per format
        charset = res.get("charset") or "unknown"
        if fmt not in charsets_per_format:
            charsets_per_format[fmt] = {}
        charsets_per_format[fmt][charset] = charsets_per_format[fmt].get(charset, 0) + 1

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

        entries = res.get("entries_count", 0)
        total_entries += entries
        entry_counts.append(entries)

        for ext in res.get("extensions", []):
            # Extensions are (ns_uri, localname) tuples; after JSON round-trip they
            # come back as lists – normalise to tuple so they are hashable dict keys.
            ext_key = tuple(ext) if isinstance(ext, (list, tuple)) else ext
            extensions[ext_key] = extensions.get(ext_key, 0) + 1

        if res.get("updated_date"):
            last_updated_dates.append(res["updated_date"])

        # Language source tracking (Unique per feed)
        http_l = res.get("lang_http")
        feed_l = res.get("lang_feed")
        entry_ls = res.get("lang_entries", [])

        if http_l:
            lang_src_http += 1
        if feed_l:
            lang_src_feed += 1
            if http_l and http_l != feed_l:
                lang_mismatches += 1

        if entry_ls:
            lang_src_entry += 1  # How many feeds have entry-level lang
            if len(entry_ls) > 1:
                lang_multiple_in_feed += 1

            # Mismatch between entry lang and feed/http lang
            base_l = feed_l or http_l
            if base_l and any(l != base_l for l in entry_ls):
                if len(entry_ls) == 1:
                    if (
                        not feed_l
                    ):  # Only add to mismatches if we haven't already counted mismatch between http and feed
                        lang_mismatches += 1
                else:
                    # Multiple entry langs already imply some mismatch or at least complex structure
                    # We'll count it as a mismatch if any differ from the primary
                    lang_mismatches += 1

    return {
        "formats": formats,
        "languages": languages,
        "extensions": extensions,
        "entry_counts": entry_counts,
        "last_updated_dates": last_updated_dates,
        "feeds_with_content": feeds_with_content,
        "feeds_with_summary": feeds_with_summary,
        "feeds_with_neither": feeds_with_neither,
        "charsets_per_format": charsets_per_format,
        "total_entries": total_entries,
        "lang_src_http": lang_src_http,
        "lang_src_feed": lang_src_feed,
        "lang_src_entry": lang_src_entry,
        "lang_mismatches": lang_mismatches,
        "lang_multiple_in_feed": lang_multiple_in_feed,
    }


def _build_page_map(stats: Stats) -> Dict[str, Set[str]]:
    page_to_feeds: Dict[str, Set[str]] = {}
    for feed_url, domains in stats.autodiscovery_links.items():
        for domain_or_url in domains:
            if domain_or_url not in page_to_feeds:
                page_to_feeds[domain_or_url] = set()
            page_to_feeds[domain_or_url].add(feed_url)
    return page_to_feeds


def _build_site_map(stats: Stats) -> Dict[str, Set[str]]:
    site_to_feeds: Dict[str, Set[str]] = {}
    for feed_url, domains in stats.autodiscovery_links.items():
        for domain in domains:
            if domain not in site_to_feeds:
                site_to_feeds[domain] = set()
            site_to_feeds[domain].add(feed_url)
    return site_to_feeds


def _detect_duplicates(
    multi_feed_pages: Dict[str, List[str]], feed_results: Dict[str, Any]
) -> List[int]:
    duplicate_counts = []
    for page_url, feed_urls in multi_feed_pages.items():
        # Map (link, title) to feed URLs
        link_to_feeds: Dict[Tuple[Optional[str], Optional[str]], Set[str]] = {}
        for url in feed_urls:
            res = feed_results.get(url)
            if not isinstance(res, dict):
                continue
            link = res.get("link")
            title = res.get("title")
            if link or title:
                key = (link, title)
                if key not in link_to_feeds:
                    link_to_feeds[key] = set()
                link_to_feeds[key].add(url)

        # Count duplicates: If a link has 3 feeds, that's 2 duplicates.
        page_dups = 0
        for feeds in link_to_feeds.values():
            if len(feeds) > 1:
                page_dups += len(feeds) - 1
        if page_dups > 0:
            duplicate_counts.append(page_dups)
    return duplicate_counts


def _build_stacked_data(
    stats: Stats, mapping: Dict[str, Set[str]], zero_count: int
) -> Dict[str, Any]:
    # bins: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11-15, 16-20, 21-50, 51-100, 100+
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
