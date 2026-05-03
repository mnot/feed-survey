import argparse
import glob
import json
import os
from datetime import datetime
from typing import Any, Dict, Iterator, Tuple

from cc_feeds.analysis import Stats
from cc_feeds.report import generate_report
from cc_feeds.report.render import default_markdown_path


def _iter_result_records(results_dir: str) -> Iterator[Tuple[str, str, Any]]:
    for part_path in glob.glob(os.path.join(results_dir, "part-*")):
        with open(part_path, "r", encoding="utf-8") as part_file:
            for line in part_file:
                if not line.strip():
                    continue

                label = ""
                try:
                    line_parts = line.split("\t", 1)
                    if len(line_parts) < 2:
                        continue

                    label = line_parts[0].strip().strip('"').strip("'")
                    data = json.loads(line_parts[1])
                    yield part_path, label, data
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    print(f"ERROR parsing line in {part_path} (label: {label}): {exc}")


def _merge_counts(target: Dict[Any, int], source: Dict[Any, int]) -> None:
    for key, count in source.items():
        target[key] = target.get(key, 0) + count


def _merge_content_lengths(stats: Stats, counts: Dict[str, int]) -> None:
    for length, count in counts.items():
        length_int = int(length)
        stats.content_length_counts[length_int] = (
            stats.content_length_counts.get(length_int, 0) + count
        )


def _merge_int_counts(target: Dict[int, int], source: Dict[str, int]) -> None:
    for key, count in source.items():
        key_int = int(key)
        target[key_int] = target.get(key_int, 0) + count


def _merge_multi_feed_pages(stats: Stats, pages: Dict[str, Any]) -> None:
    for url, feeds in pages.items():
        if url not in stats.multi_feed_pages:
            stats.multi_feed_pages[url] = []

        existing = set(stats.multi_feed_pages[url])
        for feed_url in feeds:
            if feed_url not in existing:
                stats.multi_feed_pages[url].append(feed_url)
                existing.add(feed_url)


def _merge_hll_registers(stats: Stats, registers: Any) -> None:
    if not registers:
        return

    for i in range(stats.hll_m):
        stats.hll_registers[i] = max(stats.hll_registers[i], registers[i])


def _merge_summary(stats: Stats, data: Dict[str, Any]) -> None:
    if data.get("top_n"):
        stats.top_n = data["top_n"]

    stats.pages_seen += data.get("pages_seen", 0)
    other_max_crawl = data.get("max_crawl_time_str")
    if other_max_crawl:
        if not stats.max_crawl_time_str or other_max_crawl > stats.max_crawl_time_str:
            stats.max_crawl_time_str = other_max_crawl

    stats.feeds_sniffed += data.get("feeds_sniffed", 0)
    stats.total_entries += data.get("total_entries", 0)
    _merge_content_lengths(stats, data.get("content_length_counts", {}))

    stats.lang_src_http += data.get("lang_src_http", 0)
    stats.lang_src_feed += data.get("lang_src_feed", 0)
    stats.lang_src_entry += data.get("lang_src_entry", 0)
    stats.lang_mismatches += data.get("lang_mismatches", 0)
    stats.lang_multiple_in_feed += data.get("lang_multiple_in_feed", 0)

    stats.discovery_rel_alternate += data.get("discovery_rel_alternate", 0)
    stats.discovery_rel_feed += data.get("discovery_rel_feed", 0)
    stats.discovery_rel_both_page += data.get("discovery_rel_both_page", 0)
    stats.discovery_multi_rel_url += data.get("discovery_multi_rel_url", 0)
    stats.discovery_pages_count += data.get("discovery_pages_count", 0)
    _merge_int_counts(
        stats.discovery_links_per_page_counts,
        data.get("discovery_links_per_page_counts", {}),
    )

    _merge_multi_feed_pages(stats, data.get("multi_feed_pages", {}))
    _merge_counts(
        stats.discovery_domain_counts, data.get("discovery_domain_counts", {})
    )
    _merge_hll_registers(stats, data.get("hll_registers"))

    for site in data.get("sites_seen", []):
        stats.add_site(site)

    _merge_counts(stats.content_type_counts, data.get("content_types", {}))

    stats.pages_processed += data.get("pages_processed", 0)


def _merge_discovery(stats: Stats, data: Dict[str, Any]) -> None:
    feed_url = data.get("feed_url")
    if not feed_url:
        return

    if feed_url not in stats.autodiscovery_links:
        stats.autodiscovery_links[feed_url] = []

    existing = set(stats.autodiscovery_links[feed_url])
    for source in data.get("found_on", []):
        if source not in existing and len(existing) < 100:
            stats.autodiscovery_links[feed_url].append(source)
            existing.add(source)


def _merge_feed(stats: Stats, data: Dict[str, Any]) -> None:
    url = data.get("feed_url")
    if url:
        stats.feed_results[url] = data.get("result", data)


def _merge_legacy_stats(stats: Stats, data: Dict[str, Any]) -> None:
    temp_stats = Stats()
    temp_stats.pages_seen = data.get("pages_seen", 0)
    temp_stats.sites_seen_count = data.get("sites_seen_count", 0)
    temp_stats.discovery_pages_count = data.get("discovery_pages_count", 0)
    temp_stats.multi_feed_pages = data.get("multi_feed_pages", {})
    temp_stats.autodiscovery_links = data.get("autodiscovery_links", {})

    for url, result in data.get("feed_results", {}).items():
        if isinstance(result.get("request_time"), str):
            try:
                result["request_time"] = datetime.fromisoformat(result["request_time"])
            except (ValueError, TypeError):
                pass
        temp_stats.feed_results[url] = result

    stats.merge(temp_stats)


def _merge_record(stats: Stats, label: str, data: Any) -> None:
    if label in ("summary", "pages_processed"):
        _merge_summary(stats, data)
    elif label == "discovery":
        _merge_discovery(stats, data)
    elif label in ("feed", "status"):
        _merge_feed(stats, data)
    elif label == "discovery_count":
        stats.discovery_pages_count += int(data)
    elif label in ("stats", "full_stats"):
        _merge_legacy_stats(stats, data)


def finalize_mr_results(results_dir: str, crawl_id: str, output_path: str) -> None:
    print(f"Finalizing results from {results_dir}...")

    part_files = glob.glob(os.path.join(results_dir, "part-*"))
    if not part_files:
        print(f"No part files found in {results_dir}")
        return

    overall_stats = Stats()
    for part_path, label, data in _iter_result_records(results_dir):
        try:
            _merge_record(overall_stats, label, data)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"ERROR parsing line in {part_path} (label: {label}): {exc}")

    overall_stats.sites_seen_count = overall_stats.get_unique_sites_estimate()

    print(
        f"Aggregated {overall_stats.pages_seen} candidate responses. "
        "Generating reports..."
    )
    markdown_path = default_markdown_path(output_path)
    generate_report(overall_stats, crawl_id, output_path, markdown_path)
    print(f"HTML report generated: {output_path}")
    print(f"Markdown report generated: {markdown_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate EMR part files and render HTML and Markdown reports."
    )
    parser.add_argument("results_dir", help="Local directory containing EMR part files")
    parser.add_argument("crawl_id", help="Common Crawl crawl id for the report")
    parser.add_argument(
        "output_path",
        nargs="?",
        default="cc_feeds_report.html",
        help="HTML report output path; Markdown is written next to it",
    )
    args = parser.parse_args()

    finalize_mr_results(args.results_dir, args.crawl_id, args.output_path)


if __name__ == "__main__":
    main()
