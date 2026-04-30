# --- Python 3.13 compatibility shim (Required for mrjob < 0.7.5) ---
import sys
import types
import shlex
if "pipes" not in sys.modules:
    _pipes = types.ModuleType("pipes")
    setattr(_pipes, "quote", shlex.quote)
    sys.modules["pipes"] = _pipes

import io
import os
import traceback
from typing import Any, Dict, List, Optional, cast, Generator, Tuple

import boto3
from mrjob.job import MRJob
from mrjob.protocol import JSONProtocol
from fastwarc.warc import ArchiveIterator, WarcRecordType
from fastwarc.stream_io import PythonIOStreamAdapter

# ABSOLUTE FIRST LINE LOGGING
sys.stderr.write("DEBUG: Python interpreter started successfully\n")
sys.stderr.flush()

class CCFeedsJob(MRJob): # type: ignore[misc]
    OUTPUT_PROTOCOL = JSONProtocol
    INTERNAL_PROTOCOL = JSONProtocol

    def configure_args(self) -> None:
        super().configure_args()
        self.add_passthru_arg("--topn", type=int, default=1000000)
        self.add_passthru_arg("--limit", type=int, default=0)

    def mapper_init(self) -> None:
        try:
            sys.stderr.write("*" * 50 + "\n")
            sys.stderr.write("DEBUG: mapper_init starting\n")
            sys.path.insert(0, os.getcwd())

            try:
                # Try flat file first
                import processor # type: ignore[import-not-found]
                from processor import WarcProcessor
            except ImportError:
                from cc_feeds.processor import WarcProcessor

            self.processor = WarcProcessor(top_n=self.options.topn)
            self.count = 0
            self.processed_records = 0

            from botocore.config import Config
            self.s3 = boto3.client(
                "s3",
                region_name="us-east-1",
                config=Config(
                    read_timeout=120,
                    connect_timeout=30,
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
            sys.stderr.write("DEBUG: mapper_init finished successfully\n")
        except Exception as exc:
            sys.stderr.write(f"FATAL: mapper_init failed: {exc}\n")
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
            raise

    def mapper(self, key: Any, value: Any) -> Generator[Tuple[str, Any], None, None]:
        raw_path = str(key or value or "").strip()
        if not raw_path or raw_path.startswith("#"):
            return

        if self.options.limit and self.count >= self.options.limit:
            return
        self.count += 1
        
        if False: yield  # Ensure this is a generator
        
        try:
            if os.path.exists(raw_path):
                # Process local file with optimized stream
                with open(raw_path, "rb") as f:
                    with PythonIOStreamAdapter(f) as stream:
                        for record in ArchiveIterator(
                            stream,
                            record_types=WarcRecordType.response,
                            parse_http=False,
                        ):
                            self.processed_records += 1
                            self.processor.process_record(record)
                            if self.processed_records % 1000 == 0:
                                self.increment_counter("status", "records_processed", 1000)
                                self.set_status(f"Processed {self.processed_records} records...")
            else:
                # Fetch from S3 using optimized download_file (multi-threaded)
                # This is much faster than streaming Body for large files
                import tempfile
                bucket = "commoncrawl"
                key_path = raw_path
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".warc.gz") as tmp:
                    temp_path = tmp.name
                
                try:
                    self.s3.download_file(
                        bucket, key_path, temp_path,
                        ExtraArgs={'RequestPayer': 'requester'}
                    )

                    with open(temp_path, "rb") as f:
                        with PythonIOStreamAdapter(f) as stream:
                            for record in ArchiveIterator(
                                stream,
                                record_types=WarcRecordType.response,
                                parse_http=False,
                            ):
                                self.processed_records += 1
                                self.processor.process_record(record)

                                # Progress heartbeat
                                if self.processed_records % 1000 == 0:
                                    self.increment_counter("status", "records_processed", 1000)
                                    sites_count = len(self.processor.stats.sites_seen)
                                    self.set_status(f"File {self.count}: {raw_path} | {self.processed_records} recs | {sites_count} sites")
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
        except Exception as e:
            sys.stderr.write(f"ERROR processing {raw_path}: {e}\n")
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()

    def json_safe(self, obj: Any) -> Any:
        import datetime
        import time
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, time.struct_time):
            return list(obj[:6])
        if isinstance(obj, dict):
            return {str(k): self.json_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.json_safe(i) for i in obj]
        return obj

    def serialize_stats(self, stats: Any) -> Dict[str, Any]:
        return cast(Dict[str, Any], self.json_safe({
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
        }))

    def mapper_final(self) -> Generator[Tuple[str, Any], None, None]:
        # Yield the bulk of the stats under one key for merging
        yield "stats", self.serialize_stats(self.processor.stats)
        
        # Also yield individual feed results to avoid one huge JSON blob
        for feed_url, result in self.processor.stats.feed_results.items():
            yield f"feed:{feed_url}", self.json_safe(result)
            
        # Yield discovery links
        for feed_url, domains in self.processor.stats.autodiscovery_links.items():
            yield f"discovery:{feed_url}", domains

    def combiner(self, key: str, values: Generator[Any, None, None]) -> Generator[Tuple[str, Any], None, None]:
        if key == "stats":
            merged = None
            for val in values:
                if merged is None:
                    merged = val
                    continue
                merged["pages_seen"] += val.get("pages_seen", 0)
                merged["pages_processed"] += val.get("pages_processed", 0)
                merged["feeds_sniffed"] += val.get("feeds_sniffed", 0)
                merged["total_entries"] += val.get("total_entries", 0)
                
                # Merge HLL
                oh = val.get("hll_registers")
                if oh:
                    for i in range(len(merged["hll_registers"])):
                        merged["hll_registers"][i] = max(merged["hll_registers"][i], oh[i])
                
                # Merge Content Types
                for ct, count in val.get("content_type_counts", {}).items():
                    merged["content_type_counts"][ct] = merged["content_type_counts"].get(ct, 0) + count
                    
                # Merge Max Crawl Time
                other_time = val.get("max_crawl_time_str")
                if other_time:
                    if not merged.get("max_crawl_time_str") or other_time > merged["max_crawl_time_str"]:
                        merged["max_crawl_time_str"] = other_time
                    
                # Merge Content Lengths (handling string keys from JSON)
                clc = val.get("content_length_counts", {})
                if "content_length_counts" not in merged: merged["content_length_counts"] = {}
                for length, count in clc.items():
                    merged["content_length_counts"][length] = merged["content_length_counts"].get(length, 0) + count
                    
                # Merge Discovery Domain Counts
                ddc = val.get("discovery_domain_counts", {})
                if "discovery_domain_counts" not in merged: merged["discovery_domain_counts"] = {}
                for url, count in ddc.items():
                    merged["discovery_domain_counts"][url] = merged["discovery_domain_counts"].get(url, 0) + count
                    
            yield key, merged

        elif key.startswith("discovery:"):
            # Merge domain samples early to reduce shuffle volume
            all_sources = set()
            for sources in values:
                all_sources.update(sources)
                if len(all_sources) >= 100:
                    break
            yield key, list(all_sources)[:100]

        elif key.startswith("feed:"):
            # Just take the first one; they should be identical
            yield key, next(values)

    def reducer_init(self) -> None:
        sys.path.insert(0, os.getcwd())
        try:
            from cc_feeds.processor import Stats
        except ImportError:
            from processor import Stats  # type: ignore
        self.Stats = Stats

    def reducer(self, key: str, values: Generator[Any, None, None]) -> Generator[Tuple[str, Any], None, None]:
        try:
            if key == "stats":
                # Merge global counters
                final_stats = self.Stats()
                for val in values:
                    # Direct merge from dict to avoid Stats object creation overhead
                    final_stats.pages_seen += val.get("pages_seen", 0)
                    final_stats.pages_processed += val.get("pages_processed", 0)
                    final_stats.feeds_sniffed += val.get("feeds_sniffed", 0)
                    final_stats.total_entries += val.get("total_entries", 0)
                    final_stats.lang_src_http += val.get("lang_src_http", 0)
                    final_stats.lang_src_feed += val.get("lang_src_feed", 0)
                    final_stats.lang_src_entry += val.get("lang_src_entry", 0)
                    final_stats.lang_mismatches += val.get("lang_mismatches", 0)
                    final_stats.lang_multiple_in_feed += val.get("lang_multiple_in_feed", 0)
                    final_stats.discovery_rel_alternate += val.get("discovery_rel_alternate", 0)
                    final_stats.discovery_rel_feed += val.get("discovery_rel_feed", 0)
                    final_stats.discovery_rel_both_page += val.get("discovery_rel_both_page", 0)
                    final_stats.discovery_multi_rel_url += val.get("discovery_multi_rel_url", 0)
                    final_stats.discovery_pages_count += val.get("discovery_pages_count", 0)
                    
                    # Merge Max Crawl Time
                    other_time = val.get("max_crawl_time_str")
                    if other_time:
                        if not final_stats.max_crawl_time_str or other_time > final_stats.max_crawl_time_str:
                            final_stats.max_crawl_time_str = other_time
                    
                    # Merge HLL
                    oh = val.get("hll_registers")
                    if oh:
                        for i in range(final_stats.hll_m):
                            final_stats.hll_registers[i] = max(final_stats.hll_registers[i], oh[i])
                    
                    # Merge content types
                    for ct, count in val.get("content_type_counts", {}).items():
                        final_stats.content_type_counts[ct] = final_stats.content_type_counts.get(ct, 0) + count
                        
                    # Merge content lengths (handling string keys from JSON)
                    for length, count in val.get("content_length_counts", {}).items():
                        l_int = int(length)
                        final_stats.content_length_counts[l_int] = final_stats.content_length_counts.get(l_int, 0) + count
                    
                    # Merge discovery domain counts
                    for url, count in val.get("discovery_domain_counts", {}).items():
                        final_stats.discovery_domain_counts[url] = final_stats.discovery_domain_counts.get(url, 0) + count

                    # Merge multi_feed_pages (limit memory)
                    if len(final_stats.multi_feed_pages) < 10000:
                        for p_url, f_urls in val.get("multi_feed_pages", {}).items():
                            if p_url not in final_stats.multi_feed_pages:
                                final_stats.multi_feed_pages[p_url] = f_urls
                
                yield "summary", {
                    "pages_seen": final_stats.pages_seen,
                    "max_crawl_time_str": final_stats.max_crawl_time_str,
                    "hll_registers": final_stats.hll_registers,
                    "content_types": final_stats.content_type_counts,
                    "content_length_counts": final_stats.content_length_counts,
                    "discovery_domain_counts": final_stats.discovery_domain_counts,
                    "feeds_sniffed": final_stats.feeds_sniffed,
                    "pages_processed": final_stats.pages_processed,
                    "total_entries": final_stats.total_entries,
                    "lang_src_http": final_stats.lang_src_http,
                    "lang_src_feed": final_stats.lang_src_feed,
                    "discovery_pages_count": final_stats.discovery_pages_count,
                    "discovery_rel_alternate": final_stats.discovery_rel_alternate,
                    "discovery_rel_feed": final_stats.discovery_rel_feed,
                    "discovery_rel_both_page": final_stats.discovery_rel_both_page,
                    "discovery_multi_rel_url": final_stats.discovery_multi_rel_url,
                    "multi_feed_pages": final_stats.multi_feed_pages
                }
            
            elif key.startswith("discovery:"):
                feed_url = key.split(":", 1)[1]
                all_sources = set()
                for sources in values:
                    all_sources.update(sources)
                    if len(all_sources) >= 100:
                        break
                yield "discovery", {"feed_url": feed_url, "found_on": list(all_sources)[:100]}
            
            elif key.startswith("feed:"):
                feed_url = key.split(":", 1)[1]
                result = next(values)
                yield "feed", {"feed_url": feed_url, "result": result}
                yield "heartbeat", "found_one_feed"

        except Exception as exc:
            sys.stderr.write(f"FATAL: reducer failed: {exc}\n")
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
            raise

if __name__ == "__main__":
    CCFeedsJob.run()
