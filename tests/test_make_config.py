import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _make(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "--no-print-directory", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_show_config_uses_overrides() -> None:
    result = _make(
        "show-config",
        "CONFIG=/dev/null",
        "OUTPUT_DIR=s3://example/results/",
        "PATHS_PREFIX=s3://example/paths/",
        "WHEEL_S3_PATH=s3://example/wheels/",
    )

    assert result.returncode == 0
    assert "CONFIG=/dev/null" in result.stdout
    assert "OUTPUT_DIR=s3://example/results/" in result.stdout
    assert "PATHS_PREFIX=s3://example/paths/" in result.stdout
    assert "WHEEL_S3_PATH=s3://example/wheels/" in result.stdout


def test_s3_config_missing() -> None:
    result = _make("check-s3-config", "CONFIG=/dev/null")

    assert result.returncode != 0
    assert "Set OUTPUT_DIR" in result.stdout


def test_s3_config_placeholder() -> None:
    result = _make(
        "check-s3-config",
        "CONFIG=/dev/null",
        "OUTPUT_DIR=s3://YOUR-BUCKET/results/",
        "PATHS_PREFIX=s3://example/paths/",
        "WHEEL_S3_PATH=s3://example/wheels/",
    )

    assert result.returncode != 0
    assert "Replace YOUR-BUCKET" in result.stdout


def test_emr_dry_run_tranco_alias() -> None:
    result = _make(
        "-n",
        "test-emr",
        "CONFIG=/dev/null",
        "OUTPUT_DIR=s3://example/results/",
        "PATHS_PREFIX=s3://example/paths/",
        "WHEEL_S3_PATH=s3://example/wheels/",
        "LIMIT=2",
    )

    assert result.returncode == 0
    assert "#top-1m-sites.csv" in result.stdout
    assert "--cleanup TMP" in result.stdout
    assert "--limit 2" in result.stdout


def test_emr_guard_first() -> None:
    result = _make("-n", "test-emr", "CONFIG=/dev/null")

    assert result.returncode == 0
    assert result.stdout.index("Set OUTPUT_DIR") < result.stdout.index(
        "FEED_SURVEY_CACHE_DIR"
    )


def test_upload_guard_first() -> None:
    result = _make("-n", "upload-wheels", "CONFIG=/dev/null")

    assert result.returncode == 0
    assert result.stdout.index("Set OUTPUT_DIR") < result.stdout.index(
        "mkdir -p wheels"
    )
