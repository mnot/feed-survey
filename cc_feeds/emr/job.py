import random
import sys
import time
import traceback
from typing import Any, Generator, Iterator, Tuple

from cc_feeds.emr.compat import install_mrjob_pipes_compat

install_mrjob_pipes_compat()

# pylint: disable=wrong-import-position,wrong-import-order,ungrouped-imports
from mrjob.job import MRJob
from mrjob.protocol import JSONProtocol

from cc_feeds.analysis import WarcProcessor
from cc_feeds.emr.stats_wire import (
    feed_record,
    json_safe,
    merge_source_samples,
    merge_stats_values,
    reduce_stats,
    serialize_stats,
    summary_record,
)
from cc_feeds.emr.warc_source import create_s3_client, iter_response_records

# ABSOLUTE FIRST LINE LOGGING
sys.stderr.write("DEBUG: Python interpreter started successfully\n")
sys.stderr.flush()


class CCFeedsJob(MRJob):  # type: ignore[misc]
    # pylint: disable=abstract-method,attribute-defined-outside-init
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

            self.processor = WarcProcessor(top_n=self.options.topn)
            self.count = 0
            self.processed_records = 0
            # Stagger initial S3 downloads to avoid thundering herd when all
            # mappers start simultaneously and hit the same S3 partition.
            self._s3_jitter = random.uniform(0, 30)
            self.s3 = create_s3_client()
            sys.stderr.write("DEBUG: mapper_init finished successfully\n")
        except Exception as exc:
            sys.stderr.write(f"FATAL: mapper_init failed: {exc}\n")
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
            raise

    def mapper(self, key: Any, value: Any) -> Iterator[Tuple[str, Any]]:
        raw_path = str(key or value or "").strip()
        if not raw_path or raw_path.startswith("#"):
            return

        if self.options.limit and self.count >= self.options.limit:
            return
        self.count += 1

        try:
            sys.stderr.write(f"INFO: starting WARC {self.count}: {raw_path}\n")
            sys.stderr.flush()
            if self.count == 1 and self._s3_jitter > 0:
                sys.stderr.write(f"INFO: jitter sleep {self._s3_jitter:.1f}s\n")
                sys.stderr.flush()
                time.sleep(self._s3_jitter)
            self.set_status(f"Downloading WARC {self.count}: {raw_path}")
            for record in iter_response_records(
                raw_path, self.s3, self._download_heartbeat
            ):
                self.processed_records += 1
                self.processor.process_record(record)

                if self.processed_records % 1000 == 0:
                    self.increment_counter("status", "records_processed", 1000)
                    sites_count = len(self.processor.stats.sites_seen)
                    self.set_status(
                        f"File {self.count}: {raw_path} | "
                        f"{self.processed_records} recs | {sites_count} sites"
                    )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            sys.stderr.write(f"ERROR processing {raw_path}: {exc}\n")
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
        return
        yield

    def _download_heartbeat(self, raw_path: str) -> None:
        self.set_status(f"Downloading WARC {self.count}: {raw_path}")
        sys.stderr.write(f"INFO: still downloading WARC {self.count}: {raw_path}\n")
        sys.stderr.flush()

    def mapper_final(self) -> Generator[Tuple[str, Any], None, None]:
        # Yield the bulk of the stats under one key for merging
        yield "stats", serialize_stats(self.processor.stats)

        # Also yield individual feed results to avoid one huge JSON blob
        for feed_url, result in self.processor.stats.feed_results.items():
            yield f"feed:{feed_url}", json_safe(result)

        # Yield discovery links
        for feed_url, domains in self.processor.stats.autodiscovery_links.items():
            yield f"discovery:{feed_url}", domains

    def combiner(
        self, key: str, values: Generator[Any, None, None]
    ) -> Generator[Tuple[str, Any], None, None]:
        if key == "stats":
            yield key, merge_stats_values(values)

        elif key.startswith("discovery:"):
            yield key, merge_source_samples(values)

        elif key.startswith("feed:"):
            # Just take the first one; they should be identical
            for value in values:
                yield key, value
                return

    def reducer(
        self, key: str, values: Generator[Any, None, None]
    ) -> Generator[Tuple[str, Any], None, None]:
        try:
            if key == "stats":
                yield "summary", summary_record(reduce_stats(values))

            elif key.startswith("discovery:"):
                feed_url = key.split(":", 1)[1]
                yield "discovery", {
                    "feed_url": feed_url,
                    "found_on": merge_source_samples(values),
                }

            elif key.startswith("feed:"):
                yield feed_record(key, values)
                yield "heartbeat", "found_one_feed"

        except Exception as exc:
            sys.stderr.write(f"FATAL: reducer failed: {exc}\n")
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
            raise


def main() -> None:
    CCFeedsJob.run()


if __name__ == "__main__":
    main()
