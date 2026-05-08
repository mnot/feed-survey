# Web Feed Survey (`feed-survey`)

A high-performance, distributed survey of RSS/Atom feed usage, autodiscovery, and quality in Common Crawl using AWS EMR.

## Overview

`feed-survey` uses MapReduce to process Common Crawl WARC files in parallel. It measures feed autodiscovery, parses RSS/Atom feed candidates, and renders HTML and Markdown reports from the aggregated results.

The HTML report is intended for visual exploration. The Markdown sibling uses
plain sections and tables so the same run can be re-read, compared, or ingested
by analysis tools without scraping the visual report.

## Key Features

- **Distributed MapReduce**: Built on `mrjob` for seamless scaling from a few instances to hundreds of nodes on AWS EMR.
- **Python 3.12 on EMR**: Uses modern Python syntax and efficient libraries (`fastwarc`, `lxml`) for maximum throughput.
- **Automatic Result Sync**: The build system automatically syncs results from S3 back to your local machine upon completion.
- **Tranco Filtering**: Built-in support for filtering analysis to the Tranco Top-1M, using Tranco's subdomain-inclusive list by default and Public Suffix List site normalization.
- **Platform Fingerprints**: Conservative CMS/framework hints from HTML pages, feed headers, and feed generator elements, with report-time quality comparisons.

## Quick Start (EMR)

### 1. Prerequisites
- **AWS CLI**: Installed and configured (`aws configure`).
- **EMR Roles**: Create the default roles once per account:
  ```bash
  aws emr create-default-roles
  ```
- **Local Cache**: The tool requires the Tranco list locally to upload to workers. `make emr` and `make test-emr` populate it automatically when missing; to do it explicitly:
  ```bash
  make tranco-cache
  ```

### 2. Local Setup
```bash
# Clone and set up a virtual environment
git clone https://github.com/mnot/feed-survey.git
cd feed-survey
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Local Usage
You can run the analysis on your own machine for debugging. This uses the `local` runner and does not require AWS.

```bash
# Run a one-WARC local analysis and render test_report.html and test_report.md.
make local-report
```

You can also inspect one live URL and get Markdown diagnostics:

```bash
feed-survey-probe https://example.com/feed.xml
```

HTML responses report RSS/Atom autodiscovery links. Feed responses report
parser output, language/date/content signals, extensions, fingerprints, and the
same operational quality score used by the generated reports.

### 3. Run a Smoke Test (EMR)
The `test-emr` target runs a single WARC file through a small EMR cluster to verify your AWS environment is ready.
```bash
make test-emr
```
To run a larger sample, set `LIMIT`, e.g. `make test-emr LIMIT=50`.
*Results will be automatically downloaded to `results/test-XXXXXXXX/`.*

### 4. Run the Full Crawl
Once validated, launch the full analysis across the current Common Crawl index.
```bash
make emr
```

## Configuration

### `feed-survey.mk`
This is the main run configuration loaded by `make`. Edit it directly for your
environment, or pass another make fragment with `CONFIG=/path/to/config.mk`.

- **`CRAWL_ID`**: The Common Crawl index to process.
- **`TOP_N`**: Tranco cutoff for EMR runs, applied to registrable sites after Public Suffix List normalization. Private suffixes such as `blogspot.com` and `github.io` make hosted sub-sites count independently.
- **`TRANCO_LIST`**: Tranco ranking flavor for `TOP_N` scoping. Defaults to `subdomains`, which uses Tranco's list with subdomains included before normalizing to registrable sites. Set `TRANCO_LIST=standard` to use Tranco's domain-only Top-1M.
- **`OUTPUT_DIR` / `PATHS_PREFIX` / `WHEEL_S3_PATH`**: S3 locations for EMR results, split WARC path inputs, and dependency wheels.
- **`MAP_TASKS` / `REDUCES`**: Full-run map chunking and reducer count.
- **`TEST_MAP_TASKS` / `TEST_REDUCES`**: Smoke-test map chunking and reducer count.
- **`MRJOB_CONFIG` / `MRJOB_TEST_CONFIG`**: mrjob cluster configuration files.
- **`MRJOB_CLEANUP`**: mrjob cleanup mode after successful EMR runs. Defaults to `TMP`, which removes temporary working data but keeps logs available for timing/debugging. Set `MRJOB_CLEANUP=ALL` to restore mrjob's default successful-run cleanup.
- **`TRANCO_CACHE_DIR`**: Local cache directory used by `make tranco-cache`; the selected Tranco CSV is normalized to registrable sites once locally and uploaded to EMR workers as `top-1m-sites.csv`.
- **`MOCK_REPORT` / `RESULTS_DIR`**: Local report output and re-render inputs.

### `mrjob.conf`
Control EMR cluster shape and instance types. The make targets supply bootstrap
commands, dependency-wheel location, and the Tranco upload file from
`feed-survey.mk`.

- **`TargetOnDemandCapacity`**: The default full run uses 30 core xlarge instances plus one master, leaving a little headroom below a 128 vCPU on-demand quota.
- **`instance_fleets`**: Defines the mix of m5, r5, and c5 instances EMR can choose from.

### `Makefile`
The Makefile is the command surface. It loads `feed-survey.mk`, supports
`CONFIG=...` overrides, and keeps generated reports under `results/` unless a
target explicitly writes a local scratch report.

Run `make help` for the local development, report, EMR, and wheel targets.

## Project Structure

- `feed_survey/emr/`: EMR orchestration, WARC input, and MapReduce wire-format code.
- `feed_survey/analysis/`: Core logic for parsing WARC records and extracting feed metadata.
- `feed_survey/report/`: Report-time aggregation, quality scoring, and HTML/Markdown rendering.
- `feed_survey/probe.py`: Single-URL Markdown diagnostics for feeds and HTML autodiscovery.
- `feed_survey/commoncrawl.py`: Common Crawl metadata and WARC path discovery.
- `feed_survey/tranco.py`: Tranco list loading for top-site scoping.
- `feed_survey/url.py`: URL normalization, host extraction, and registrable-site helpers.
- `feed_survey/download.py`: Shared download and cache helpers.
- `tests/`: Unit tests and integration tests.
- `tests/fixtures/`: Small local fixtures and profiling helpers used by tests and smoke runs.
- `docs/`: Research notes and plans for future analysis dimensions.
- `feed-survey.mk`: Make-readable run configuration for crawl, S3, EMR sizing, and cache paths.
- `mrjob.conf`: EMR orchestration settings (Python 3.12, dependencies, instance fleets).
- `.mrjobignore`: Prevents local virtual environments and caches from being uploaded to workers.

## Local Development & Testing

Useful local development targets:

```bash
make test
make typecheck
make lint
make mock-report
make check
```

## Cost Notes

Runtime and cost depend on the selected crawl, EMR instance mix, regional pricing,
spot availability, and whether slow WARC files dominate the tail of the job. Use
`make test-emr LIMIT=<n>` to check throughput in your account before starting a
full run, and use the EMR console or Cost Explorer for current pricing.
