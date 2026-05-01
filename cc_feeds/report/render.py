import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union, cast

import dateutil.parser
from jinja2 import Environment, FileSystemLoader

from cc_feeds.analysis import Stats
from cc_feeds.report.quality import score_feed

# Known namespace URI → conventional prefix
_NS_PREFIXES: Dict[str, str] = {
    "http://purl.org/dc/elements/1.1/": "dc",
    "http://purl.org/dc/terms/": "dcterms",
    "http://search.yahoo.com/mrss/": "media",
    "http://purl.org/rss/1.0/modules/content/": "content",
    "http://purl.org/rss/1.0/modules/slash/": "slash",
    "http://purl.org/rss/1.0/modules/syndication/": "sy",
    "http://www.w3.org/2003/01/geo/wgs84_pos#": "geo",
    "http://www.georss.org/georss/": "georss",
    "http://schemas.google.com/g/2005#": "gd",
    "http://wellformedweb.org/CommentAPI/": "wfw",
    "http://webfeeds.org/rss/1.0": "webfeeds",
    "http://purl.org/rss/1.0/modules/company/": "co",
    "http://purl.org/rss/1.0/modules/event/": "ev",
}

# (max_age_days, label) pairs for recency CDFs – ordered oldest→newest so the
# CDF reads left-to-right as "older threshold → higher coverage"
_CDF_BREAKPOINTS: List[Tuple[int, str]] = [
    (0, "Today"),
    (1, "1 day"),
    (3, "3 days"),
    (7, "1 week"),
    (14, "2 weeks"),
    (30, "1 month"),
    (90, "3 months"),
    (180, "6 months"),
    (365, "1 year"),
    (730, "2 years"),
    (10000, "All"),  # sentinel — catches everything, always 100 %
]


def _format_extension(ext: Any) -> str:
    """Format a (namespace_uri, localname) tuple as a readable prefix:local string."""
    if isinstance(ext, (tuple, list)) and len(ext) == 2:
        ns, local = str(ext[0]), str(ext[1])
        prefix = _NS_PREFIXES.get(ns)
        if prefix:
            return f"{prefix}:{local}"
        # Derive a short prefix from the URI
        stripped = ns.rstrip("/#")
        part = stripped.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if part:
            return f"{part}:{local}"
        return local
    return str(ext)


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
    agg = _aggregate_feed_data(all_valid_results)

    feeds_with_autodiscovery = len(discovered_results)
    feeds_without_autodiscovery = len(all_valid_results) - feeds_with_autodiscovery

    # --- Content-type distribution (collapsed) ---
    content_types_collapsed: Dict[str, int] = {
        "HTML": 0,
        "Atom": 0,
        "RSS": 0,
        "JSON Feed": 0,
        "Other XML": 0,
        "Other": 0,
    }
    for ct, count in stats.content_type_counts.items():
        ct_l = ct.lower()
        if "text/html" in ct_l or "application/xhtml" in ct_l:
            content_types_collapsed["HTML"] += count
        elif "atom" in ct_l:
            content_types_collapsed["Atom"] += count
        elif "rss" in ct_l:
            content_types_collapsed["RSS"] += count
        elif "feed+json" in ct_l or ("json" in ct_l and "html" not in ct_l):
            content_types_collapsed["JSON Feed"] += count
        elif "xml" in ct_l:
            content_types_collapsed["Other XML"] += count
        else:
            content_types_collapsed["Other"] += count

    # --- Content profile distribution ---
    content_profile_dist: Dict[str, int] = {
        "html": 0,
        "plain": 0,
        "xhtml": 0,
        "mixed": 0,
        "unknown": 0,
    }
    for res in all_valid_results.values():
        profile = res.get("content_type_profile", "unknown") or "unknown"
        content_profile_dist[profile] = content_profile_dist.get(profile, 0) + 1

    # --- Language count per feed histogram ---
    lang_count_hist: Dict[str, int] = {"0": 0, "1": 0, "2": 0, "3+": 0}
    for res in all_valid_results.values():
        n = len(res.get("all_languages") or [])
        if n == 0:
            lang_count_hist["0"] += 1
        elif n == 1:
            lang_count_hist["1"] += 1
        elif n == 2:
            lang_count_hist["2"] += 1
        else:
            lang_count_hist["3+"] += 1

    # --- Discovery Mapping ---
    page_to_feeds = _build_page_map(stats)
    site_to_feeds = _build_site_map(stats)

    discovery_page_counts = [len(f) for f in page_to_feeds.values()]
    total_pages = stats.pages_seen
    zero_pages = max(0, total_pages - len(page_to_feeds))

    discovery_per_page_hist = make_histogram(discovery_page_counts, bins="discovery")
    discovery_per_page_hist.pop("0", None)

    discovery_site_counts = [len(f) for f in site_to_feeds.values()]
    total_sites = getattr(stats, "sites_seen_count", len(stats.sites_seen))
    zero_sites = max(0, total_sites - len(site_to_feeds))

    discovery_per_site_hist = make_histogram(discovery_site_counts, bins="discovery")
    discovery_per_site_hist.pop("0", None)

    # Duplicate detection
    duplicate_counts = _detect_duplicates(stats.multi_feed_pages, stats.feed_results)
    pages_with_duplicates = len(duplicate_counts)
    multi_feed_pages_total = len(stats.multi_feed_pages)
    duplicate_prevalence_pct = (
        round(pages_with_duplicates / multi_feed_pages_total * 100, 1)
        if multi_feed_pages_total
        else 0.0
    )

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

    # --- Crawl time reference ---
    max_crawl_time = None
    if stats.max_crawl_time_str:
        try:
            max_crawl_time = dateutil.parser.parse(stats.max_crawl_time_str)
            if max_crawl_time.tzinfo is None:
                max_crawl_time = max_crawl_time.replace(tzinfo=timezone.utc)
        except Exception:
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

    feed_recency_cdf = _build_recency_cdf(all_valid_results, "updated_date", now)
    entry_recency_cdf = _build_recency_cdf(feeds_with_entries, "newest_entry_date", now)
    oldest_entry_cdf = _build_recency_cdf(feeds_with_entries, "oldest_entry_date", now)

    # --- Quality distribution (recomputed at report time so algo changes are free) ---
    quality_hist: Dict[str, int] = {f"{i/10:.1f}–{(i+1)/10:.1f}": 0 for i in range(10)}
    quality_scores: List[float] = []
    fmt_quality: Dict[str, List[float]] = {}
    for res in all_valid_results.values():
        q = score_feed(res, now)
        quality_scores.append(q)
        bin_idx = min(int(q * 10), 9)
        label = f"{bin_idx/10:.1f}–{(bin_idx+1)/10:.1f}"
        quality_hist[label] += 1
        fmt = res.get("format") or "unknown"
        fmt_quality.setdefault(fmt, []).append(q)
    mean_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

    format_quality_rows: List[Dict[str, Any]] = []
    for fmt, scores in fmt_quality.items():
        n = len(scores)
        mean_q: float = sum(scores) / n
        format_quality_rows.append(
            {
                "fmt": fmt,
                "count": n,
                "mean": round(mean_q, 3),
                "high_pct": round(sum(1 for s in scores if s >= 0.7) / n * 100, 1),
                "mid_pct": round(sum(1 for s in scores if 0.4 <= s < 0.7) / n * 100, 1),
                "low_pct": round(sum(1 for s in scores if s < 0.4) / n * 100, 1),
            }
        )
    # Order by mean quality descending for the chart
    format_quality_rows.sort(key=lambda r: cast(float, r["mean"]), reverse=True)

    # --- Quality: with vs without autodiscovery ---
    def _quality_dist(results: Dict[str, Any]) -> Dict[str, Any]:
        """Percentage histogram + mean quality for a set of feed results."""
        scores = [score_feed(res, now) for res in results.values()]
        n = len(scores)
        bins = [f"{i/10:.1f}–{(i+1)/10:.1f}" for i in range(10)]
        hist = {b: 0 for b in bins}
        for q in scores:
            hist[f"{min(int(q*10),9)/10:.1f}–{(min(int(q*10),9)+1)/10:.1f}"] += 1
        pct = {b: round(hist[b] / n * 100, 1) if n else 0.0 for b in bins}
        mean = round(sum(scores) / n, 3) if n else 0.0
        return {"labels": bins, "pct": list(pct.values()), "mean": mean, "n": n}

    no_autodiscovery_results = {
        url: res for url, res in all_valid_results.items() if url not in discovered_urls
    }
    autodiscovery_quality = _quality_dist(discovered_results)
    no_autodiscovery_quality = _quality_dist(no_autodiscovery_results)

    # --- Sort & format ---
    formats = sorted(agg["formats"].items(), key=lambda x: x[1], reverse=True)
    languages = sorted(agg["languages"].items(), key=lambda x: x[1], reverse=True)
    errors = sorted(stats.error_types.items(), key=lambda x: x[1], reverse=True)
    total_errors = sum(c for _, c in errors)

    # Extensions: format as prefix:local, deduplicate, top 15
    ext_formatted: Dict[str, int] = {}
    for ext, count in agg["extensions"].items():
        label = _format_extension(ext)
        ext_formatted[label] = ext_formatted.get(label, 0) + count
    extensions = sorted(ext_formatted.items(), key=lambda x: x[1], reverse=True)[:15]

    # --- Template data ---
    report_stats = {
        "pages_seen": stats.pages_seen,
        "max_crawl_time": max_crawl_time,
        "sites_seen": total_sites,
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
        "content_types_collapsed": content_types_collapsed,
        "content_profile_dist": content_profile_dist,
        "lang_count_hist": lang_count_hist,
        "quality_hist": quality_hist,
        "mean_quality": round(mean_quality, 3),
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
        discovery_per_page_hist=discovery_per_page_hist,
        discovery_per_site_hist=discovery_per_site_hist,
        stacked_page_json=json.dumps(stacked_page),
        stacked_site_json=json.dumps(stacked_site),
        charsets_per_format=agg["charsets_per_format"],
        content_length_hist=make_histogram(stats.content_length_counts, bins="natural"),
        entry_counts_hist=make_histogram(agg["entry_counts"], bins="entries"),
        feed_recency_cdf=json.dumps(feed_recency_cdf),
        entry_recency_cdf=json.dumps(entry_recency_cdf),
        oldest_entry_cdf=json.dumps(oldest_entry_cdf),
        n_zero_entry=n_zero_entry,
        quality_hist=json.dumps(quality_hist),
        format_quality_json=json.dumps(format_quality_rows),
        format_quality_rows=format_quality_rows,
        autodiscovery_quality=autodiscovery_quality,
        no_autodiscovery_quality=no_autodiscovery_quality,
        autodiscovery_quality_json=json.dumps(autodiscovery_quality),
        no_autodiscovery_quality_json=json.dumps(no_autodiscovery_quality),
        total_pages_f=format_number(stats.pages_seen),
        pages_with_auto_f=format_number(
            stats.discovery_pages_count
            if stats.discovery_pages_count > 0
            else len(stats.autodiscovery_links)
        ),
        zero_pages_f=format_number(zero_pages),
        total_sites_f=format_number(total_sites),
        sites_with_auto_f=format_number(len(site_to_feeds)),
        zero_sites_f=format_number(zero_sites),
        pages_with_duplicates=pages_with_duplicates,
        duplicate_prevalence_pct=duplicate_prevalence_pct,
        multi_feed_pages_total=multi_feed_pages_total,
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


def _build_recency_cdf(
    results: Dict[str, Any], key: str, now: datetime
) -> Dict[str, Any]:
    """
    Build a CDF for recency data.

    For each breakpoint in _CDF_BREAKPOINTS, computes the percentage of feeds
    whose *key* date is at most that many days before *now*.  Feeds with no date
    are included in the total (denominator) but never counted as covered, so
    they suppress the curve toward 100 %.

    Returns {"labels": [...], "data": [...]} suitable for a Chart.js line chart.
    """
    ages: List[int] = []
    total = len(results)
    for info in results.values():
        val = info.get(key)
        if not val:
            continue
        try:
            dt = datetime(
                val[0], val[1], val[2], val[3], val[4], val[5], tzinfo=timezone.utc
            )
            ages.append(max(0, (now - dt).days))
        except (ValueError, TypeError, IndexError):
            pass

    ages.sort()
    n = len(ages)  # feeds that have a date — the CDF denominator
    no_date = total - n  # feeds excluded (no date available)
    labels: List[str] = []
    data: List[float] = []
    for days, label in _CDF_BREAKPOINTS:
        # bisect_right equivalent
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if ages[mid] <= days:
                lo = mid + 1
            else:
                hi = mid
        pct = round(lo / n * 100, 1) if n else 0.0
        labels.append(label)
        data.append(pct)
    return {"labels": labels, "data": data, "no_date": no_date}
