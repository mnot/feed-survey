import gzip
import pickle
from pathlib import Path
from typing import Any

from feed_survey.analysis.stats import Stats
from feed_survey.emr.job import CCFeedsJob
from feed_survey.emr.timing import summarize_logs
from feed_survey.emr.warc_worker import WarcWorkerResult

# pylint: disable=protected-access


def test_failure_log(capsys: Any) -> None:
    job = CCFeedsJob()
    job.count = 7
    counters: dict[tuple[str, str], int] = {}

    def increment_counter(group: str, counter: str, amount: int) -> None:
        counters[(group, counter)] = counters.get((group, counter), 0) + amount

    job.increment_counter = increment_counter

    job._record_warc_failure("crawl-data/example.warc.gz", -6)

    captured = capsys.readouterr()
    assert "ERROR: failed WARC 7: crawl-data/example.warc.gz" in captured.err
    assert "exit_code=-6 signal=6" in captured.err
    assert counters[("status", "warcs_failed")] == 1
    assert counters[("status", "warc_signal_6")] == 1


def test_child_result(monkeypatch: Any) -> None:
    job = CCFeedsJob()
    job.options = type(
        "Options",
        (),
        {"topn": 500000, "tranco_list": "subdomains", "limit": 0},
    )()

    child_stats = Stats()
    child_stats.pages_seen = 2
    child_stats.responses_processed = 3
    child_stats.feed_results = {"https://example.com/feed.xml": {"type": "RSS 2.0"}}
    worker_result = WarcWorkerResult(
        stats=child_stats,
        records_seen=4,
        total_ms=100,
        process_ms=30,
        iterator_ms=70,
    )

    def fake_process_warc_to_file(*args: object) -> None:
        result_path = str(args[1])
        with open(result_path, "wb") as result_file:
            pickle.dump(worker_result, result_file)

    monkeypatch.setattr(
        "feed_survey.emr.job.process_warc_to_file", fake_process_warc_to_file
    )

    result = job._process_warc_in_child("crawl-data/example.warc.gz")

    assert result is not None
    assert result.records_seen == 4
    assert result.total_ms == 100
    assert result.stats.pages_seen == 2
    assert result.stats.feed_results == {
        "https://example.com/feed.xml": {"type": "RSS 2.0"}
    }


def test_timing_failures(tmp_path: Path) -> None:
    container = tmp_path / "container_1"
    container.mkdir()
    stderr = container / "stderr.gz"
    with gzip.open(stderr, "wt", encoding="utf-8") as gzip_file:
        gzip_file.write("DEBUG: mapper_init finished successfully in 50ms\n")
        gzip_file.write("INFO: jitter sleep 1.0s\n")
        gzip_file.write(
            "INFO: finished WARC 1: ok.warc.gz | records=10 "
            "total_ms=100 process_ms=20 iterator_download_ms=80\n"
        )
        gzip_file.write(
            "ERROR: failed WARC 2: bad.warc.gz | exit_code=-6 signal=6 "
            "child process did not produce results\n"
        )

    warcs, failures, mappers = summarize_logs(tmp_path)

    assert [warc.path for warc in warcs] == ["ok.warc.gz"]
    assert failures[0].path == "bad.warc.gz"
    assert failures[0].exit_code == "-6"
    assert failures[0].signal == "6"
    assert mappers[0].warcs == 1
