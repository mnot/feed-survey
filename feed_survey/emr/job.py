import random
import sys
import time
import traceback
import tempfile
from multiprocessing import get_context
from typing import Any, Generator, Iterator, Tuple

from feed_survey.emr.compat import install_mrjob_pipes_compat

install_mrjob_pipes_compat()

# pylint: disable=wrong-import-position,wrong-import-order,ungrouped-imports
from mrjob.job import MRJob
from mrjob.protocol import JSONProtocol

from feed_survey.analysis import WarcProcessor
from feed_survey.emr.stats_wire import (
    feed_discovery_count_record,
    feed_source_fingerprint_record,
    feed_record,
    json_safe,
    merge_count_values,
    merge_source_samples,
    merge_stats_values,
    reduce_stats,
    serialize_stats,
    summary_record,
)
from feed_survey.emr.warc_worker import (
    WarcWorkerResult,
    load_warc_worker_result,
    process_warc_to_file,
)

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
        self.add_passthru_arg(
            "--tranco-list",
            choices=("subdomains", "standard"),
            default="subdomains",
            help="Tranco list flavor used for TOP_N scoping",
        )
        self.add_passthru_arg("--limit", type=int, default=0)

    def mapper_init(self) -> None:
        init_start = time.perf_counter()
        try:
            sys.stderr.write("*" * 50 + "\n")
            sys.stderr.write("DEBUG: mapper_init starting\n")

            self.processor = WarcProcessor(
                top_n=self.options.topn,
                tranco_include_subdomains=self.options.tranco_list == "subdomains",
            )
            self.processor.stats.run_limit = self.options.limit or 0
            self.count = 0
            self.processed_records = 0
            # Stagger initial S3 downloads to avoid thundering herd when all
            # mappers start simultaneously and hit the same S3 partition.
            self._s3_jitter = random.uniform(0, 30)
            init_ms = int((time.perf_counter() - init_start) * 1000)
            self.increment_counter("timing", "mapper_init_ms", init_ms)
            sys.stderr.write(
                f"DEBUG: mapper_init finished successfully in {init_ms}ms\n"
            )
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
            records_before = self.processed_records
            if self.count == 1 and self._s3_jitter > 0:
                sys.stderr.write(f"INFO: jitter sleep {self._s3_jitter:.1f}s\n")
                sys.stderr.flush()
                time.sleep(self._s3_jitter)
                self.increment_counter(
                    "timing", "jitter_ms", int(self._s3_jitter * 1000)
                )
            self.set_status(f"Downloading WARC {self.count}: {raw_path}")
            result = self._process_warc_in_child(raw_path)
            if result is None:
                return

            self.processed_records += result.records_seen
            self.processor.stats.merge(result.stats)
            warc_ms = result.total_ms
            process_ms = result.process_ms
            iterator_ms = result.iterator_ms
            records_in_warc = self.processed_records - records_before
            self.increment_counter("status", "records_processed", records_in_warc)
            self.increment_counter("timing", "warc_total_ms", warc_ms)
            self.increment_counter("timing", "record_process_ms", process_ms)
            self.increment_counter("timing", "iterator_download_ms", iterator_ms)
            self.increment_counter("timing", "warcs_completed", 1)
            self.increment_counter("timing", "records_seen", records_in_warc)
            sys.stderr.write(
                "INFO: finished WARC "
                f"{self.count}: {raw_path} | records={records_in_warc} "
                f"total_ms={warc_ms} process_ms={process_ms} "
                f"iterator_download_ms={iterator_ms}\n"
            )
            sys.stderr.flush()
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

    def _process_warc_in_child(self, raw_path: str) -> WarcWorkerResult | None:
        with tempfile.NamedTemporaryFile(delete=True) as result_file:
            context = get_context("fork")
            process = context.Process(
                target=process_warc_to_file,
                args=(
                    raw_path,
                    result_file.name,
                    self.options.topn,
                    self.options.tranco_list == "subdomains",
                    self.options.limit or 0,
                ),
            )
            process.start()
            while process.is_alive():
                process.join(timeout=30)
                if process.is_alive():
                    self._download_heartbeat(raw_path)

            if process.exitcode != 0:
                self._record_warc_failure(raw_path, process.exitcode)
                return None

            try:
                return load_warc_worker_result(result_file.name)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                sys.stderr.write(
                    "ERROR: failed WARC "
                    f"{self.count}: {raw_path} | result_read_error={exc}\n"
                )
                sys.stderr.write(traceback.format_exc())
                sys.stderr.flush()
                self.increment_counter("status", "warcs_failed", 1)
                self.increment_counter("status", "warc_result_read_error", 1)
                return None

    def _record_warc_failure(self, raw_path: str, exit_code: int | None) -> None:
        exit_label = "unknown" if exit_code is None else str(exit_code)
        signal_label = ""
        if exit_code is not None and exit_code < 0:
            signal_label = f" signal={-exit_code}"
            self.increment_counter("status", f"warc_signal_{-exit_code}", 1)
        elif exit_code is not None:
            self.increment_counter("status", f"warc_exit_{exit_code}", 1)
        self.increment_counter("status", "warcs_failed", 1)
        sys.stderr.write(
            "ERROR: failed WARC "
            f"{self.count}: {raw_path} | exit_code={exit_label}{signal_label} "
            "child process did not produce results\n"
        )
        sys.stderr.flush()

    def mapper_final(self) -> Generator[Tuple[str, Any], None, None]:
        # Yield the bulk of the stats under one key for merging
        yield "stats", serialize_stats(self.processor.stats)

        # Also yield individual feed results to avoid one huge JSON blob
        for feed_url, result in self.processor.stats.feed_results.items():
            yield f"feed:{feed_url}", json_safe(result)

        # Yield discovery links
        for feed_url, sites in self.processor.stats.autodiscovery_links.items():
            yield f"discovery:{feed_url}", sites

        # Yield per-feed discovery link counts separately so the summary reducer
        # stays bounded at full-crawl scale.
        for feed_url, count in self.processor.stats.discovery_domain_counts.items():
            yield f"discoverycount:{feed_url}", count

        # Yield feed-source fingerprints separately to avoid one giant summary
        # reducer carrying a feed-url keyed map for the whole crawl.
        for feed_url, counts in self.processor.stats.feed_source_fingerprints.items():
            yield f"feedfp:{feed_url}", counts

    def combiner(
        self, key: str, values: Generator[Any, None, None]
    ) -> Generator[Tuple[str, Any], None, None]:
        if key == "stats":
            yield key, merge_stats_values(values)

        elif key.startswith("discovery:"):
            yield key, merge_source_samples(values)

        elif key.startswith("discoverycount:"):
            yield feed_discovery_count_record(key, values)[1]["count"]

        elif key.startswith("feedfp:"):
            yield key, merge_count_values(values)

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

            elif key.startswith("discoverycount:"):
                yield feed_discovery_count_record(key, values)

            elif key.startswith("feedfp:"):
                yield feed_source_fingerprint_record(key, values)

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
