from pathlib import Path
from types import SimpleNamespace

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from feed_survey.emr import finalize, split_paths
from feed_survey.report import mock


def test_split_paths_cli_limit(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    source = tmp_path / "warc.paths.txt"
    source.write_text("a.warc.gz\nb.warc.gz\nc.warc.gz\n", encoding="utf-8")
    uploads: list[list[str]] = []

    def fake_run(args: list[str], check: bool) -> None:
        uploads.append(args)
        assert check is True

    monkeypatch.setattr("feed_survey.emr.split_paths.subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["split_paths", str(source), "s3://example/chunks", "2", "2"],
    )

    split_paths.main()

    output = capsys.readouterr().out
    assert "Limited to first 2 paths." in output
    assert "Done: 2 chunks at s3://example/chunks/" in output
    assert uploads == [["aws", "s3", "sync", uploads[0][3], "s3://example/chunks/"]]


def test_finalize_cli_default(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_finalize(results_dir: str, crawl_id: str, output_path: str) -> None:
        calls.append((results_dir, crawl_id, output_path))

    monkeypatch.setattr(finalize, "finalize_mr_results", fake_finalize)
    monkeypatch.setattr("sys.argv", ["finalize", "results/test", "CC-MAIN-2026-12"])

    finalize.main()

    assert calls == [("results/test", "CC-MAIN-2026-12", "feed_survey_report.html")]


def test_mock_report_cli_default(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[object, str, str]] = []

    def fake_generate_report(stats: object, crawl_id: str, output_path: str) -> None:
        calls.append((stats, crawl_id, output_path))

    monkeypatch.setattr(
        mock,
        "build_mock_stats",
        lambda: SimpleNamespace(feed_results={}, autodiscovery_links={}),
    )
    monkeypatch.setattr(
        mock,
        "generate_report",
        fake_generate_report,
    )
    monkeypatch.setattr("sys.argv", ["mock"])

    mock.main()

    assert calls[0][1:] == (mock.CRAWL_ID, "mock_report.html")
