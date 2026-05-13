"""Crash-isolated WARC processing for EMR mappers."""

# pylint: disable=broad-exception-caught

from __future__ import annotations

import pickle
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Any, cast

from feed_survey.analysis.processor import WarcProcessor
from feed_survey.analysis.stats import Stats
from feed_survey.emr.warc_source import create_s3_client, iter_response_records


@dataclass
class WarcWorkerResult:
    stats: Stats
    records_seen: int
    total_ms: int
    process_ms: int
    iterator_ms: int


def process_warc_to_file(
    raw_path: str,
    result_path: str,
    top_n: int,
    tranco_include_subdomains: bool,
    run_limit: int,
) -> None:
    """Process one WARC and write the result to ``result_path``.

    This function is intended to run in a child process. Native crashes in
    fastwarc/decompression/parsing should kill only this child, leaving the
    parent mapper free to log the WARC path and continue.
    """

    worker_start = time.perf_counter()
    processor = WarcProcessor(
        top_n=top_n,
        tranco_include_subdomains=tranco_include_subdomains,
    )
    processor.stats.run_limit = run_limit
    s3_client: Any = create_s3_client()
    records_seen = 0
    processing_time = 0.0

    try:
        for record in iter_response_records(raw_path, s3_client, _download_heartbeat):
            records_seen += 1
            process_start = time.perf_counter()
            processor.process_record(record)
            processing_time += time.perf_counter() - process_start

        total_ms = int((time.perf_counter() - worker_start) * 1000)
        process_ms = int(processing_time * 1000)
        result = WarcWorkerResult(
            stats=processor.stats,
            records_seen=records_seen,
            total_ms=total_ms,
            process_ms=process_ms,
            iterator_ms=max(0, total_ms - process_ms),
        )
        with open(result_path, "wb") as result_file:
            pickle.dump(result, result_file)
    except Exception as exc:
        sys.stderr.write(f"ERROR: WARC worker failed for {raw_path}: {exc}\n")
        sys.stderr.write(traceback.format_exc())
        sys.stderr.flush()
        raise


def load_warc_worker_result(path: str) -> WarcWorkerResult:
    with open(path, "rb") as result_file:
        return cast(WarcWorkerResult, pickle.load(result_file))


def _download_heartbeat(raw_path: str) -> None:
    sys.stderr.write(f"INFO: child still downloading WARC: {raw_path}\n")
    sys.stderr.flush()
