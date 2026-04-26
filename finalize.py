import json
import os
import sys
import glob
from datetime import datetime, timezone
from cc_feeds.processor import Stats
from cc_feeds.report import generate_report

def finalize_mr_results(results_dir: str, crawl_id: str, output_path: str) -> None:
    print(f"Finalizing results from {results_dir}...")
    
    overall_stats = Stats()
    
    # Iterate over all part files
    part_files = glob.glob(os.path.join(results_dir, "part-*"))
    if not part_files:
        print(f"No part files found in {results_dir}")
        return

    for part_path in part_files:
        with open(part_path, 'r') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    # Strip whitespace and handle potential quotes in the label
                    line_parts = line.split('\t', 1)
                    if len(line_parts) < 2: continue
                    
                    label = line_parts[0].strip().strip('"').strip("'")
                    data_str = line_parts[1]
                    data = json.loads(data_str)
                    
                    if label == 'summary' or label == 'pages_processed':
                        overall_stats.pages_seen += data.get("pages_seen", 0)
                        other_max_crawl = data.get("max_crawl_time_str")
                        if other_max_crawl:
                            if not overall_stats.max_crawl_time_str or other_max_crawl > overall_stats.max_crawl_time_str:
                                overall_stats.max_crawl_time_str = other_max_crawl
                        overall_stats.feeds_sniffed += data.get("feeds_sniffed", 0)
                        overall_stats.total_entries += data.get("total_entries", 0)
                        
                        # Merge content length histogram
                        clc = data.get("content_length_counts", {})
                        for length, count in clc.items():
                            l_int = int(length)
                            overall_stats.content_length_counts[l_int] = overall_stats.content_length_counts.get(l_int, 0) + count

                        overall_stats.lang_src_http += data.get("lang_src_http", 0)
                        overall_stats.lang_src_feed += data.get("lang_src_feed", 0)
                        overall_stats.lang_src_entry += data.get("lang_src_entry", 0)
                        overall_stats.lang_mismatches += data.get("lang_mismatches", 0)
                        overall_stats.lang_multiple_in_feed += data.get("lang_multiple_in_feed", 0)
                        overall_stats.discovery_rel_alternate += data.get("discovery_rel_alternate", 0)
                        overall_stats.discovery_rel_feed += data.get("discovery_rel_feed", 0)
                        overall_stats.discovery_rel_both_page += data.get("discovery_rel_both_page", 0)
                        overall_stats.discovery_multi_rel_url += data.get("discovery_multi_rel_url", 0)
                        overall_stats.discovery_pages_count += data.get("discovery_pages_count", 0)
                        
                        # Merge multi_feed_pages (Dict[url, List[feed_urls]])
                        mfp = data.get("multi_feed_pages", {})
                        for url, feeds in mfp.items():
                            if url not in overall_stats.multi_feed_pages:
                                overall_stats.multi_feed_pages[url] = []
                            # Merge unique feeds for this page
                            existing = set(overall_stats.multi_feed_pages[url])
                            for f in feeds:
                                if f not in existing:
                                    overall_stats.multi_feed_pages[url].append(f)

                        # Merge discovery domain counts
                        ddc = data.get("discovery_domain_counts", {})
                        for feed_url, count in ddc.items():
                            overall_stats.discovery_domain_counts[feed_url] = overall_stats.discovery_domain_counts.get(feed_url, 0) + count

                        # Handle HLL registers
                        other_hll = data.get("hll_registers")
                        if other_hll:
                            for i in range(overall_stats.hll_m):
                                overall_stats.hll_registers[i] = max(overall_stats.hll_registers[i], other_hll[i])
                        
                        # Handle legacy sites_seen if present
                        sites_seen = data.get("sites_seen", [])
                        if sites_seen:
                            for site in sites_seen:
                                overall_stats.add_site(site)
                        
                        # Merge content type counts
                        cts = data.get("content_types", {})
                        for ct, count in cts.items():
                            overall_stats.content_type_counts[ct] = overall_stats.content_type_counts.get(ct, 0) + count
                            
                        # Merge other summary metrics
                        overall_stats.feeds_sniffed += data.get("feeds_sniffed", 0)
                        overall_stats.total_entries += data.get("total_entries", 0)
                        overall_stats.pages_processed += data.get("pages_processed", 0)
                    
                    elif label == 'discovery':
                        # Handle individual discovery records
                        feed_url = data.get("feed_url")
                        found_on = data.get("found_on", [])
                        if feed_url:
                            if feed_url not in overall_stats.autodiscovery_links:
                                overall_stats.autodiscovery_links[feed_url] = []
                            # Deduplicate page URLs across different part files
                            existing = set(overall_stats.autodiscovery_links[feed_url])
                            for source in found_on:
                                if source not in existing and len(existing) < 100:
                                    overall_stats.autodiscovery_links[feed_url].append(source)
                                    existing.add(source)
                        
                    elif label in ['feed', 'status']:
                        url = data.get("feed_url")
                        res = data.get("result", data)
                        if url:
                            overall_stats.feed_results[url] = res
                            
                    elif label == 'discovery_count':
                        overall_stats.discovery_pages_count += int(data)
                        
                    elif label in ['stats', 'full_stats']:
                        temp_stats = Stats()
                        temp_stats.pages_seen = data.get("pages_seen", 0)
                        temp_stats.sites_seen_count = data.get("sites_seen_count", 0)
                        temp_stats.discovery_pages_count = data.get("discovery_pages_count", 0)
                        temp_stats.multi_feed_pages = data.get("multi_feed_pages", {})
                        temp_stats.autodiscovery_links = data.get("autodiscovery_links", {})
                        
                        raw_feeds = data.get("feed_results", {})
                        for url, res in raw_feeds.items():
                            if isinstance(res.get("request_time"), str):
                                try:
                                    res["request_time"] = datetime.fromisoformat(res["request_time"])
                                except (ValueError, TypeError):
                                    pass
                            temp_stats.feed_results[url] = res
                        overall_stats.merge(temp_stats)
                        
                except Exception as e:
                    print(f"ERROR parsing line in {part_path} (label: {label}): {e}")
                    # continue to next line
                    continue

    # Calculate final HLL estimate from merged registers
    overall_stats.sites_seen_count = overall_stats.get_unique_sites_estimate()
    
    print(f"Aggregated {overall_stats.pages_seen} pages. Generating official report...")
    generate_report(overall_stats, crawl_id, output_path)
    print(f"Official report generated: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python finalize.py <results_dir> <crawl_id> [output_file]")
        sys.exit(1)
    
    dir_path = sys.argv[1]
    cid = sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else "cc_feeds_report.html"
    finalize_mr_results(dir_path, cid, out)
