import datetime
import time
from typing import Any, Dict, Generator, Tuple, cast

from cc_feeds.analysis import Stats


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
                "max_crawl_time_str": stats.max_crawl_time_str,
                "hll_registers": stats.hll_registers,
                "content_type_counts": stats.content_type_counts,
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
                "discovery_pages_count": stats.discovery_pages_count,
                "multi_feed_pages": stats.multi_feed_pages,
                "content_length_counts": stats.content_length_counts,
                "discovery_domain_counts": stats.discovery_domain_counts,
                "top_n": stats.top_n,
            }
        ),
    )


def merge_serialized_stats(merged: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    merged["pages_seen"] += incoming.get("pages_seen", 0)
    merged["pages_processed"] += incoming.get("pages_processed", 0)
    merged["feeds_sniffed"] += incoming.get("feeds_sniffed", 0)
    merged["total_entries"] += incoming.get("total_entries", 0)

    incoming_hll = incoming.get("hll_registers")
    if incoming_hll:
        for i in range(len(merged["hll_registers"])):
            merged["hll_registers"][i] = max(
                merged["hll_registers"][i], incoming_hll[i]
            )

    for content_type, count in incoming.get("content_type_counts", {}).items():
        merged["content_type_counts"][content_type] = (
            merged["content_type_counts"].get(content_type, 0) + count
        )

    other_time = incoming.get("max_crawl_time_str")
    if other_time:
        if (
            not merged.get("max_crawl_time_str")
            or other_time > merged["max_crawl_time_str"]
        ):
            merged["max_crawl_time_str"] = other_time

    if "content_length_counts" not in merged:
        merged["content_length_counts"] = {}
    for length, count in incoming.get("content_length_counts", {}).items():
        merged["content_length_counts"][length] = (
            merged["content_length_counts"].get(length, 0) + count
        )

    if "discovery_domain_counts" not in merged:
        merged["discovery_domain_counts"] = {}
    for url, count in incoming.get("discovery_domain_counts", {}).items():
        merged["discovery_domain_counts"][url] = (
            merged["discovery_domain_counts"].get(url, 0) + count
        )


def merge_stats_values(values: Generator[Any, None, None]) -> Dict[str, Any]:
    merged = None
    for value in values:
        if merged is None:
            merged = value
        else:
            merge_serialized_stats(merged, value)

    return cast(Dict[str, Any], merged)


def merge_source_samples(values: Generator[Any, None, None]) -> list[Any]:
    sources = set()
    for value in values:
        sources.update(value)
        if len(sources) >= 100:
            break
    return list(sources)[:100]


def reduce_stats(values: Generator[Any, None, None]) -> Stats:
    final_stats = Stats()
    for value in values:
        final_stats.pages_seen += value.get("pages_seen", 0)
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
        final_stats.discovery_pages_count += value.get("discovery_pages_count", 0)

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

        for length, count in value.get("content_length_counts", {}).items():
            length_int = int(length)
            final_stats.content_length_counts[length_int] = (
                final_stats.content_length_counts.get(length_int, 0) + count
            )

        for url, count in value.get("discovery_domain_counts", {}).items():
            final_stats.discovery_domain_counts[url] = (
                final_stats.discovery_domain_counts.get(url, 0) + count
            )

        if len(final_stats.multi_feed_pages) < 10000:
            for page_url, feed_urls in value.get("multi_feed_pages", {}).items():
                if page_url not in final_stats.multi_feed_pages:
                    final_stats.multi_feed_pages[page_url] = feed_urls

    return final_stats


def summary_record(stats: Stats) -> Dict[str, Any]:
    return {
        "pages_seen": stats.pages_seen,
        "max_crawl_time_str": stats.max_crawl_time_str,
        "hll_registers": stats.hll_registers,
        "content_types": stats.content_type_counts,
        "content_length_counts": stats.content_length_counts,
        "discovery_domain_counts": stats.discovery_domain_counts,
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
        "multi_feed_pages": stats.multi_feed_pages,
        "top_n": stats.top_n,
    }


def feed_record(
    key: str, values: Generator[Any, None, None]
) -> Tuple[str, Dict[str, Any]]:
    feed_url = key.split(":", 1)[1]
    for result in values:
        return "feed", {"feed_url": feed_url, "result": result}
    return "feed", {"feed_url": feed_url, "result": None}
