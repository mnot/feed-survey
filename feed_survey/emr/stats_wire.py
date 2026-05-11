import datetime
import time
from typing import Any, Dict, Generator, Tuple, cast

from feed_survey.analysis import Stats


def json_safe(obj: Any) -> Any:
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, time.struct_time):
        return list(obj[:6])
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(item) for item in obj]
    return obj


def serialize_stats(stats: Stats) -> Dict[str, Any]:
    return cast(
        Dict[str, Any],
        json_safe(
            {
                "pages_seen": stats.pages_seen,
                "responses_processed": stats.responses_processed,
                "max_crawl_time_str": stats.max_crawl_time_str,
                "hll_registers": stats.hll_registers,
                "content_type_counts": stats.content_type_counts,
                "error_types": stats.error_types,
                "feeds_sniffed": stats.feeds_sniffed,
                "pages_processed": stats.pages_processed,
                "total_entries": stats.total_entries,
                "lang_src_http": stats.lang_src_http,
                "lang_src_feed": stats.lang_src_feed,
                "lang_src_entry": stats.lang_src_entry,
                "lang_mismatches": stats.lang_mismatches,
                "lang_multiple_in_feed": stats.lang_multiple_in_feed,
                "discovery_rel_alternate": stats.discovery_rel_alternate,
                "discovery_rel_feed": stats.discovery_rel_feed,
                "discovery_rel_both_page": stats.discovery_rel_both_page,
                "discovery_multi_rel_url": stats.discovery_multi_rel_url,
                "discovery_link_rel_both": stats.discovery_link_rel_both,
                "discovery_link_rel_both_page": stats.discovery_link_rel_both_page,
                "discovery_pages_count": stats.discovery_pages_count,
                "discovery_links_per_page_counts": stats.discovery_links_per_page_counts,
                "discovery_feeds_per_site_counts": (
                    stats.discovery_feeds_per_site_counts
                ),
                "multi_feed_pages": stats.multi_feed_pages,
                "html_fingerprint_counts": stats.html_fingerprint_counts,
                "html_fingerprint_auto_counts": (stats.html_fingerprint_auto_counts),
                "html_fp_pages": stats.html_fp_pages,
                "html_fp_auto_pages": (stats.html_fp_auto_pages),
                "content_length_counts": stats.content_length_counts,
                "top_n": stats.top_n,
                "tranco_include_subdomains": stats.tranco_include_subdomains,
                "run_limit": stats.run_limit,
            }
        ),
    )


def merge_serialized_stats(merged: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    merged.setdefault("responses_processed", merged.get("pages_seen", 0))
    merged.setdefault(
        "discovery_link_rel_both", merged.get("discovery_multi_rel_url", 0)
    )
    merged.setdefault("discovery_link_rel_both_page", 0)
    merged["pages_seen"] += incoming.get("pages_seen", 0)
    merged["responses_processed"] += incoming.get("responses_processed", 0)
    merged["pages_processed"] += incoming.get("pages_processed", 0)
    merged["feeds_sniffed"] += incoming.get("feeds_sniffed", 0)
    merged["total_entries"] += incoming.get("total_entries", 0)
    merged["lang_src_http"] += incoming.get("lang_src_http", 0)
    merged["lang_src_feed"] += incoming.get("lang_src_feed", 0)
    merged["lang_src_entry"] += incoming.get("lang_src_entry", 0)
    merged["lang_mismatches"] += incoming.get("lang_mismatches", 0)
    merged["lang_multiple_in_feed"] += incoming.get("lang_multiple_in_feed", 0)
    merged["discovery_rel_alternate"] += incoming.get("discovery_rel_alternate", 0)
    merged["discovery_rel_feed"] += incoming.get("discovery_rel_feed", 0)
    merged["discovery_rel_both_page"] += incoming.get("discovery_rel_both_page", 0)
    merged["discovery_multi_rel_url"] += incoming.get("discovery_multi_rel_url", 0)
    merged["discovery_link_rel_both"] += incoming.get("discovery_link_rel_both", 0)
    merged["discovery_link_rel_both_page"] += incoming.get(
        "discovery_link_rel_both_page", 0
    )
    merged["discovery_pages_count"] += incoming.get("discovery_pages_count", 0)

    incoming_top_n = incoming.get("top_n")
    if incoming_top_n is not None:
        current_top_n = merged.get("top_n")
        if current_top_n is None or incoming_top_n > current_top_n:
            merged["top_n"] = incoming_top_n
            merged["tranco_include_subdomains"] = incoming.get(
                "tranco_include_subdomains", True
            )
    if incoming.get("tranco_include_subdomains") is False:
        merged["tranco_include_subdomains"] = False
    merged["run_limit"] = max(merged.get("run_limit", 0), incoming.get("run_limit", 0))

    incoming_hll = incoming.get("hll_registers")
    if incoming_hll:
        for i in range(len(merged["hll_registers"])):
            merged["hll_registers"][i] = max(
                merged["hll_registers"][i], incoming_hll[i]
            )

    _merge_count_map(merged, incoming, "content_type_counts")
    _merge_count_map(merged, incoming, "error_types")

    other_time = incoming.get("max_crawl_time_str")
    if other_time:
        if (
            not merged.get("max_crawl_time_str")
            or other_time > merged["max_crawl_time_str"]
        ):
            merged["max_crawl_time_str"] = other_time

    _merge_count_map(merged, incoming, "content_length_counts")
    _merge_count_map(merged, incoming, "discovery_links_per_page_counts")
    _merge_count_map(merged, incoming, "discovery_feeds_per_site_counts")

    if "multi_feed_pages" not in merged:
        merged["multi_feed_pages"] = {}
    if len(merged["multi_feed_pages"]) < 10000:
        for page_url, feed_urls in incoming.get("multi_feed_pages", {}).items():
            if page_url not in merged["multi_feed_pages"]:
                merged["multi_feed_pages"][page_url] = feed_urls

    for field in (
        "html_fingerprint_counts",
        "html_fingerprint_auto_counts",
    ):
        _merge_count_map(merged, incoming, field)
    merged["html_fp_pages"] = merged.get("html_fp_pages", 0) + incoming.get(
        "html_fp_pages", 0
    )
    merged["html_fp_auto_pages"] = merged.get("html_fp_auto_pages", 0) + incoming.get(
        "html_fp_auto_pages", 0
    )


def merge_stats_values(values: Generator[Any, None, None]) -> Dict[str, Any]:
    merged = None
    for value in values:
        if merged is None:
            merged = value
        else:
            merge_serialized_stats(merged, value)

    return cast(Dict[str, Any], merged)


def _merge_count_map(
    merged: Dict[str, Any], incoming: Dict[str, Any], field: str
) -> None:
    target = merged.setdefault(field, {})
    for key, count in incoming.get(field, {}).items():
        target[key] = target.get(key, 0) + count


def merge_unique_values(values: Generator[Any, None, None]) -> list[Any]:
    sources = set()
    for value in values:
        sources.update(value)
    return list(sources)


def merge_count_values(values: Generator[Any, None, None]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        for label, count in value.items():
            counts[label] = counts.get(label, 0) + count
    return counts


def reduce_stats(values: Generator[Any, None, None]) -> Stats:
    final_stats = Stats()
    for value in values:
        incoming_top_n = value.get("top_n")
        if incoming_top_n is not None:
            if final_stats.top_n is None or incoming_top_n > final_stats.top_n:
                final_stats.top_n = incoming_top_n
                final_stats.tranco_include_subdomains = value.get(
                    "tranco_include_subdomains", True
                )
        if value.get("tranco_include_subdomains") is False:
            final_stats.tranco_include_subdomains = False
        final_stats.run_limit = max(final_stats.run_limit, value.get("run_limit", 0))

        final_stats.pages_seen += value.get("pages_seen", 0)
        final_stats.responses_processed += value.get("responses_processed", 0)
        final_stats.pages_processed += value.get("pages_processed", 0)
        final_stats.feeds_sniffed += value.get("feeds_sniffed", 0)
        final_stats.total_entries += value.get("total_entries", 0)
        final_stats.lang_src_http += value.get("lang_src_http", 0)
        final_stats.lang_src_feed += value.get("lang_src_feed", 0)
        final_stats.lang_src_entry += value.get("lang_src_entry", 0)
        final_stats.lang_mismatches += value.get("lang_mismatches", 0)
        final_stats.lang_multiple_in_feed += value.get("lang_multiple_in_feed", 0)
        final_stats.discovery_rel_alternate += value.get("discovery_rel_alternate", 0)
        final_stats.discovery_rel_feed += value.get("discovery_rel_feed", 0)
        final_stats.discovery_rel_both_page += value.get("discovery_rel_both_page", 0)
        final_stats.discovery_multi_rel_url += value.get("discovery_multi_rel_url", 0)
        final_stats.discovery_link_rel_both += value.get("discovery_link_rel_both", 0)
        final_stats.discovery_link_rel_both_page += value.get(
            "discovery_link_rel_both_page", 0
        )
        final_stats.discovery_pages_count += value.get("discovery_pages_count", 0)
        for link_count, page_count in value.get(
            "discovery_links_per_page_counts", {}
        ).items():
            link_count_int = int(link_count)
            final_stats.discovery_links_per_page_counts[link_count_int] = (
                final_stats.discovery_links_per_page_counts.get(link_count_int, 0)
                + page_count
            )
        for link_count, site_count in value.get(
            "discovery_feeds_per_site_counts", {}
        ).items():
            link_count_int = int(link_count)
            final_stats.discovery_feeds_per_site_counts[link_count_int] = (
                final_stats.discovery_feeds_per_site_counts.get(link_count_int, 0)
                + site_count
            )

        other_time = value.get("max_crawl_time_str")
        if other_time:
            if (
                not final_stats.max_crawl_time_str
                or other_time > final_stats.max_crawl_time_str
            ):
                final_stats.max_crawl_time_str = other_time

        incoming_hll = value.get("hll_registers")
        if incoming_hll:
            for i in range(final_stats.hll_m):
                final_stats.hll_registers[i] = max(
                    final_stats.hll_registers[i], incoming_hll[i]
                )

        for content_type, count in value.get("content_type_counts", {}).items():
            final_stats.content_type_counts[content_type] = (
                final_stats.content_type_counts.get(content_type, 0) + count
            )
        for error_type, count in value.get("error_types", {}).items():
            final_stats.error_types[error_type] = (
                final_stats.error_types.get(error_type, 0) + count
            )

        for length, count in value.get("content_length_counts", {}).items():
            length_int = int(length)
            final_stats.content_length_counts[length_int] = (
                final_stats.content_length_counts.get(length_int, 0) + count
            )

        if len(final_stats.multi_feed_pages) < 10000:
            for page_url, feed_urls in value.get("multi_feed_pages", {}).items():
                if page_url not in final_stats.multi_feed_pages:
                    final_stats.multi_feed_pages[page_url] = feed_urls

        for label, count in value.get("html_fingerprint_counts", {}).items():
            final_stats.html_fingerprint_counts[label] = (
                final_stats.html_fingerprint_counts.get(label, 0) + count
            )
        for label, count in value.get("html_fingerprint_auto_counts", {}).items():
            final_stats.html_fingerprint_auto_counts[label] = (
                final_stats.html_fingerprint_auto_counts.get(label, 0) + count
            )
        final_stats.html_fp_pages += value.get("html_fp_pages", 0)
        final_stats.html_fp_auto_pages += value.get("html_fp_auto_pages", 0)
    return final_stats


def summary_record(stats: Stats) -> Dict[str, Any]:
    return {
        "pages_seen": stats.pages_seen,
        "responses_processed": stats.responses_processed,
        "max_crawl_time_str": stats.max_crawl_time_str,
        "hll_registers": stats.hll_registers,
        "content_types": stats.content_type_counts,
        "error_types": stats.error_types,
        "content_length_counts": stats.content_length_counts,
        "feeds_sniffed": stats.feeds_sniffed,
        "pages_processed": stats.pages_processed,
        "total_entries": stats.total_entries,
        "lang_src_http": stats.lang_src_http,
        "lang_src_feed": stats.lang_src_feed,
        "lang_src_entry": stats.lang_src_entry,
        "lang_mismatches": stats.lang_mismatches,
        "lang_multiple_in_feed": stats.lang_multiple_in_feed,
        "discovery_pages_count": stats.discovery_pages_count,
        "discovery_rel_alternate": stats.discovery_rel_alternate,
        "discovery_rel_feed": stats.discovery_rel_feed,
        "discovery_rel_both_page": stats.discovery_rel_both_page,
        "discovery_multi_rel_url": stats.discovery_multi_rel_url,
        "discovery_link_rel_both": stats.discovery_link_rel_both,
        "discovery_link_rel_both_page": stats.discovery_link_rel_both_page,
        "discovery_links_per_page_counts": stats.discovery_links_per_page_counts,
        "discovery_feeds_per_site_counts": stats.discovery_feeds_per_site_counts,
        "multi_feed_pages": stats.multi_feed_pages,
        "html_fingerprint_counts": stats.html_fingerprint_counts,
        "html_fingerprint_auto_counts": (stats.html_fingerprint_auto_counts),
        "html_fp_pages": stats.html_fp_pages,
        "html_fp_auto_pages": stats.html_fp_auto_pages,
        "top_n": stats.top_n,
        "tranco_include_subdomains": stats.tranco_include_subdomains,
        "run_limit": stats.run_limit,
    }


def feed_record(
    key: str, values: Generator[Any, None, None]
) -> Tuple[str, Dict[str, Any]]:
    feed_url = key.split(":", 1)[1]
    for result in values:
        return "feed", {"feed_url": feed_url, "result": result}
    return "feed", {"feed_url": feed_url, "result": None}


def feed_source_fingerprint_record(
    key: str, values: Generator[Any, None, None]
) -> Tuple[str, Dict[str, Any]]:
    feed_url = key.split(":", 1)[1]
    return "feed_source_fingerprint", {
        "feed_url": feed_url,
        "fingerprints": merge_count_values(values),
    }


def feed_discovery_count_record(
    key: str, values: Generator[Any, None, None]
) -> Tuple[str, Dict[str, Any]]:
    feed_url = key.split(":", 1)[1]
    return "feed_discovery_count", {
        "feed_url": feed_url,
        "count": sum(int(value) for value in values),
    }


def feed_auto_site_record(
    key: str, values: Generator[Any, None, None]
) -> Tuple[str, Dict[str, Any]]:
    feed_url = key.split(":", 1)[1]
    return "feed_discovery_site_count", {
        "feed_url": feed_url,
        "count": len(merge_unique_values(values)),
    }


def site_auto_feed_record(
    _key: str, values: Generator[Any, None, None]
) -> Tuple[str, Dict[str, Any]]:
    return "site_discovery_feed_count", {
        "count": len(merge_unique_values(values)),
    }
