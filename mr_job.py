import os
import shlex
import sys
import types
import traceback

# ABSOLUTE FIRST LINE LOGGING
sys.stderr.write("DEBUG: Python interpreter started successfully\n")
sys.stderr.flush()

try:
    # Force current directory into path for EMR workers
    sys.path.insert(0, os.getcwd())

    # --- Python 3.13 compatibility shim (Required for mrjob < 0.7.5) ---
    import shlex
    import types
    if "pipes" not in sys.modules:
        _pipes = types.ModuleType("pipes")
        _pipes.quote = shlex.quote
        sys.modules["pipes"] = _pipes

    from typing import Any, Dict, Generator, Optional, Tuple
    from mrjob.job import MRJob

    class CCFeedsJob(MRJob):
        # Using default protocol (RawProtocol) for maximum compatibility

        def configure_args(self) -> None:
            super().configure_args()
            self.add_passthru_arg("--topn", type=int, default=100000)
            self.add_passthru_arg("--limit", type=int, default=0)

        def mapper_init(self) -> None:
            try:
                import requests
                try:
                    from cc_feeds.processor import WarcProcessor
                except ImportError:
                    from processor import WarcProcessor  # type: ignore
                
                self.processor = WarcProcessor(top_n=self.options.topn)
                self.count = 0
            except Exception as exc:
                sys.stderr.write(f"FATAL: mapper_init failed: {exc}\n")
                raise

        def mapper(self, key: Any, value: Any) -> Generator[Tuple[str, Any], None, None]:
            import traceback
            import requests
            from fastwarc.warc import ArchiveIterator
            
            raw_path = str(key or value or "").strip()
            if not raw_path or raw_path.startswith("#"):
                return

            if self.options.limit and self.count >= self.options.limit:
                return
            self.count += 1
            
            url = f"https://data.commoncrawl.org/{raw_path}"
            
            try:
                resp = requests.get(url, stream=True, timeout=60)
                resp.raise_for_status()
                
                for record in ArchiveIterator(resp.raw):
                    self.processor.process_record(record)
                
                yield "stats", self.serialize_stats(self.processor.stats)
            except Exception as exc:
                safe_url = url if 'url' in locals() else str(raw_path)
                sys.stderr.write(f"ERROR: {safe_url}: {exc}\n")
                sys.stderr.write(traceback.format_exc())
                sys.stderr.flush()

        def serialize_stats(self, stats: Any) -> Dict[str, Any]:
            import datetime
            
            def json_safe(obj: Any) -> Any:
                if isinstance(obj, set):
                    return list(obj)
                if isinstance(obj, datetime.datetime):
                    return obj.isoformat()
                if isinstance(obj, dict):
                    return {k: json_safe(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [json_safe(i) for i in obj]
                return obj

            return {
                "pages_seen": stats.pages_seen,
                "sites_seen": list(stats.sites_seen),
                "autodiscovery_links": stats.autodiscovery_links,
                "feed_results": json_safe(stats.feed_results)
            }

        def reducer(self, key: str, values: Generator[Dict[str, Any], None, None]) -> Generator[Tuple[str, Any], None, None]:
            import traceback
            try:
                try:
                    from cc_feeds.processor import Stats
                except ImportError:
                    from processor import Stats  # type: ignore
                    
                final_stats = Stats()
                for val in values:
                    temp = Stats()
                    temp.pages_seen = val["pages_seen"]
                    temp.sites_seen = set(val["sites_seen"])
                    temp.autodiscovery_links = val["autodiscovery_links"]
                    temp.feed_results = val["feed_results"]
                    final_stats.merge(temp)
                
                # Yield Summary
                yield "summary", {
                    "pages_processed": final_stats.pages_seen,
                    "unique_sites": len(final_stats.sites_seen)
                }
                
                # Yield each discovered feed as a separate record
                for feed_url, sources in final_stats.autodiscovery_links.items():
                    yield "discovery", {"feed_url": feed_url, "found_on": list(set(sources))}
                    
                # Yield each processed feed status
                for feed_url, result in final_stats.feed_results.items():
                    yield "status", {"feed_url": feed_url, "result": result}
            except Exception as exc:
                sys.stderr.write(f"FATAL: reducer failed: {exc}\n")
                sys.stderr.write(traceback.format_exc())
                sys.stderr.flush()
                raise

    def main():
        CCFeedsJob.run()

    if __name__ == "__main__":
        main()

except Exception as global_exc:
    import traceback
    sys.stderr.write(f"FATAL: Global script failure: {global_exc}\n")
    sys.stderr.write(traceback.format_exc())
    sys.stderr.flush()
    sys.exit(1)
