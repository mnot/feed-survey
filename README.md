# Common Crawl Feed Analysis (`cc-feeds`)

A high-performance, distributed tool to analyze the prevalence and quality of RSS/Atom feeds within the Common Crawl dataset using AWS EMR.

## Overview

`cc-feeds` uses MapReduce to process Common Crawl WARC files in parallel. It measures feed autodiscovery, fetches and parses discovered RSS/Atom feeds, and renders HTML and Markdown reports from the aggregated results.

The HTML report is intended for visual exploration. The Markdown sibling uses
plain sections and tables so the same run can be re-read, compared, or ingested
by analysis tools without scraping the visual report.

## Key Features

- **Distributed MapReduce**: Built on `mrjob` for seamless scaling from a few instances to hundreds of nodes on AWS EMR.
- **Python 3.12 on EMR**: Uses modern Python syntax and efficient libraries (`fastwarc`, `lxml`) for maximum throughput.
- **Automatic Result Sync**: The build system automatically syncs results from S3 back to your local machine upon completion.
- **Tranco Filtering**: Built-in support for filtering analysis to the Tranco Top-1M high-traffic domains.

## Quick Start (EMR)

### 1. Prerequisites
- **AWS CLI**: Installed and configured (`aws configure`).
- **EMR Roles**: Create the default roles once per account:
  ```bash
  aws emr create-default-roles
  ```
- **Local Cache**: The tool requires the Tranco list locally to upload to workers:
  ```bash
  mkdir -p ~/.cache/cc-feeds
  curl -L https://tranco-list.eu/download/K66XN/1000000 -o ~/.cache/cc-feeds/top-1m.csv
  ```

### 2. Local Setup
```bash
# Clone and set up a virtual environment
git clone https://github.com/mnot/cc-feeds.git
cd cc-feeds
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

### `mrjob.conf`
Control the cluster size and instance types.
- **`TargetOnDemandCapacity`**: The default full run uses 30 core xlarge instances plus one master, leaving a little headroom below a 128 vCPU on-demand quota.
- **`instance_fleets`**: Defines the mix of m5, r5, and c5 instances EMR can choose from.

### `Makefile`
- **`CRAWL_ID`**: The Common Crawl index to process (e.g., `CC-MAIN-2026-12`).
- **`MAP_TASKS`**: Number of WARC path chunks for a full run. The default is higher than the worker count so slow WARC files have less impact on overall progress.
- **`REDUCES`**: Number of reducers for the full EMR run.
- **`TEST_MAP_TASKS` / `TEST_REDUCES`**: Map and reduce sizing for `make test-emr`.
- **`OUTPUT_DIR`**: The S3 bucket where results and logs will be stored.
- **`MOCK_REPORT`**: HTML output path for `make mock-report`; a Markdown sibling is written automatically.
- **`RESULTS_DIR`**: Existing local result directory to re-render with `make report`, producing both `report.html` and `report.md`.

Run `make help` for the local development, report, EMR, and wheel targets.

## Project Structure

- `cc_feeds/emr/`: EMR orchestration, WARC input, and MapReduce wire-format code.
- `cc_feeds/analysis/`: Core logic for parsing WARC records and extracting feed metadata.
- `cc_feeds/report/`: Report-time aggregation, quality scoring, and HTML/Markdown rendering.
- `cc_feeds/commoncrawl.py`: Common Crawl metadata and WARC path discovery.
- `cc_feeds/tranco.py`: Tranco list loading for top-site scoping.
- `cc_feeds/url.py`: URL normalization and domain extraction helpers.
- `cc_feeds/download.py`: Shared download and cache helpers.
- `tests/`: Unit tests and integration tests.
- `tests/fixtures/`: Small local fixtures and profiling helpers used by tests and smoke runs.
- `docs/`: Research notes and plans for future analysis dimensions.
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
