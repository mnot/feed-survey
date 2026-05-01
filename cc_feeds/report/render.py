import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, cast

import dateutil.parser
from jinja2 import Environment, FileSystemLoader

from cc_feeds.analysis import Stats
from cc_feeds.report.aggregate import aggregate_feed_data
from cc_feeds.report.discovery import (
    build_page_map,
    build_site_map,
    build_stacked_data,
    detect_duplicates,
)
from cc_feeds.report.formatting import format_extension, format_number
from cc_feeds.report.histograms import build_recency_cdf, make_histogram
from cc_feeds.report.quality import score_feed


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
    page_to_feeds = build_page_map(stats)
    site_to_feeds = build_site_map(stats)

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
    duplicate_counts = detect_duplicates(stats.multi_feed_pages, stats.feed_results)
    pages_with_duplicates = len(duplicate_counts)
    multi_feed_pages_total = len(stats.multi_feed_pages)
    duplicate_prevalence_pct = (
        round(pages_with_duplicates / multi_feed_pages_total * 100, 1)
        if multi_feed_pages_total
        else 0.0
    )

    # Stacked discovery data
    stacked_page = build_stacked_data(stats, page_to_feeds, zero_pages)
    stacked_site = build_stacked_data(stats, site_to_feeds, zero_sites)
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

    feed_recency_cdf = build_recency_cdf(all_valid_results, "updated_date", now)
    entry_recency_cdf = build_recency_cdf(feeds_with_entries, "newest_entry_date", now)
    oldest_entry_cdf = build_recency_cdf(feeds_with_entries, "oldest_entry_date", now)

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
        label = format_extension(ext)
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
