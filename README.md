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
- **OPML Feed-List Reports**: Local reporting for a user's own OPML subscription list, using the same feed parsing, quality, autodiscovery, and HTML/Markdown report machinery as crawl reports.

## Install

For the standalone CLI tools (`feed-survey-probe`, `feed-survey-opml`), the
base install is lightweight and pipx-friendly — it only depends on `requests`,
`lxml`, `beautifulsoup4`, `jinja2`, `python-dateutil`, and `publicsuffix2`:

```bash
pipx install feed-survey
```

The Common Crawl / EMR pipeline is driven by `make`, not the installed CLI: it
needs the repository's `Makefile`, `mrjob.conf`, and local `feed-survey.mk`
config alongside the heavy runtime deps. To run it, clone the repo and follow
[Quick Start (EMR)](#quick-start-emr) below. `make venv` installs the `[dev]`
extra, which pulls in the `[emr]` extra (`boto3`, `fastwarc`, `mrjob`,
`tqdm`) automatically.

The EMR-only entry points (`feed-survey`, `feed-survey-job`,
`feed-survey-finalize`, `feed-survey-split-paths`) are always registered, but
running them outside the make-driven workflow means hand-supplying the cluster
config and orchestration the Makefile normally provides — not a recommended
path.

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
pip install -e ".[dev]"   # includes the emr extra

# Create your local run configuration before using EMR targets.
cp feed-survey.example.mk feed-survey.mk
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

To fetch an HTML page and then inspect the feeds it advertises:

```bash
feed-survey-probe --recursive https://example.com/
```

Recursive probing follows only the RSS/Atom URLs found in the page's
autodiscovery links, and checks at most 10 unique feed URLs by default. Use
`--max-feeds N` to change that cap.

### Analyze an OPML Feed List
For personal or ecosystem-specific audits, `feed-survey-opml` turns an OPML
subscription file into a full HTML and Markdown report without using Common
Crawl or EMR:

```bash
feed-survey-opml subscriptions.opml --output feeds-report.html
```

The same command is available through make:

```bash
make opml-report OPML=subscriptions.opml OPML_REPORT=feeds-report.html
```

The OPML path is intended for answering questions like "how healthy are the
feeds I already subscribe to?" or "what formats, languages, extensions, and
quality signals show up in this curated list?" It reuses the same parser,
quality scoring, extension analysis, platform fingerprinting, and report renderer
as the crawl pipeline.

OPML `xmlUrl` values are the primary feed inputs. When an outline also has
`url` or `htmlUrl`, the command fetches that page as HTML and reports RSS/Atom
autodiscovery properties too, so the report can distinguish feeds that are
explicitly listed in OPML from feeds that the linked site advertises. Pass
`--skip-html` if you only want to fetch the `xmlUrl` feeds. Progress is written
to standard error while feeds and pages are fetched; pass `-q` / `--quiet` to
suppress it. Fetches run in parallel by default; use `--concurrency N` to tune
the maximum number of simultaneous feed/page requests. The default is 32. Each
feed/page fetch is capped at 10 MiB by default; use `--max-bytes N` to change the
cap, or `--max-bytes 0` to disable it.

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

### Make Configuration
`feed-survey.defaults.mk` contains safe defaults for local development and
non-secret tuning. `feed-survey.mk` is your local, ignored configuration file
for AWS buckets and account-specific choices. Create it from the example:

```bash
cp feed-survey.example.mk feed-survey.mk
```

Edit `feed-survey.mk`, or pass another make fragment with
`CONFIG=/path/to/config.mk`.

Run `make show-config` to print the effective settings before starting an EMR
run.

- **`CRAWL_ID`**: The Common Crawl index to process.
- **`TOP_N`**: Tranco cutoff for EMR runs, applied to registrable sites after Public Suffix List normalization. Private suffixes such as `blogspot.com` and `github.io` make hosted sub-sites count independently.
- **`TRANCO_LIST`**: Tranco ranking flavor for `TOP_N` scoping. Defaults to `subdomains`, which uses Tranco's list with subdomains included before normalizing to registrable sites. Set `TRANCO_LIST=standard` to use Tranco's domain-only Top-1M.
- **`OUTPUT_DIR` / `PATHS_PREFIX` / `WHEEL_S3_PATH`**: S3 locations for EMR results, split WARC path inputs, and dependency wheels.
- **`MAP_TASKS` / `REDUCES`**: Full-run map chunking and reducer count.
- **`TEST_MAP_TASKS` / `TEST_REDUCES`**: Smoke-test map chunking and reducer count.
- **`MRJOB_CONFIG` / `MRJOB_TEST_CONFIG`**: mrjob cluster configuration files.
- **`MRJOB_CLEANUP`**: mrjob cleanup mode after successful EMR runs. Defaults to `TMP`, which removes temporary working data but keeps logs available for timing/debugging. Set `MRJOB_CLEANUP=ALL` to restore mrjob's default successful-run cleanup.
- **`EMR_LOG_CLUSTER_ID` / `EMR_LOG_DIR`**: Inputs for `make emr-timing`, which downloads preserved mapper stderr logs and summarizes WARC timing counters.
- **`TRANCO_CACHE_DIR`**: Local cache directory used by `make tranco-cache`; the selected Tranco CSV is normalized to registrable sites once locally and uploaded to EMR workers as `top-1m-sites.csv`.
- **`MOCK_REPORT` / `RESULTS_DIR`**: Local report output and re-render inputs.

### `mrjob.conf`
Control EMR cluster shape and instance types. The make targets supply bootstrap
commands, dependency-wheel location, and the Tranco upload file from the make
configuration.

- **`TargetOnDemandCapacity`**: The default full run uses 30 core xlarge instances plus one master, leaving a little headroom below a 128 vCPU on-demand quota.
- **`instance_fleets`**: Defines the mix of m5, r5, and c5 instances EMR can choose from.

### `Makefile`
The Makefile is the command surface. It loads `feed-survey.defaults.mk`, then
optionally loads `feed-survey.mk` or the file named by `CONFIG=...`. Generated
reports stay under `results/` unless a target explicitly writes a local scratch
report.

Run `make help` for the local development, report, EMR, and wheel targets.

## Project Structure

- `feed_survey/emr/`: EMR orchestration, WARC input, and MapReduce wire-format code.
- `feed_survey/analysis/`: Core logic for parsing WARC records and extracting feed metadata.
- `feed_survey/report/`: Report-time aggregation, quality scoring, and HTML/Markdown rendering.
- `feed_survey/probe.py`: Single-URL Markdown diagnostics for feeds and HTML autodiscovery.
- `feed_survey/opml.py`: OPML input path for local feed-list reports.
- `feed_survey/commoncrawl.py`: Common Crawl metadata and WARC path discovery.
- `feed_survey/tranco.py`: Tranco list loading for top-site scoping.
- `feed_survey/url.py`: URL normalization, host extraction, and registrable-site helpers.
- `feed_survey/download.py`: Shared download and cache helpers.
- `tests/`: Unit tests and integration tests.
- `tests/fixtures/`: Small local fixtures and profiling helpers used by tests and smoke runs.
- `docs/`: Research notes and plans for future analysis dimensions.
- `feed-survey.defaults.mk`: Tracked make defaults for crawl, EMR sizing, and cache paths.
- `feed-survey.example.mk`: Example local configuration with placeholder S3 paths.
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
make emr-timing EMR_LOG_CLUSTER_ID=j-...
```

## Cost Notes

Runtime and cost depend on the selected crawl, EMR instance mix, regional pricing,
spot availability, and whether slow WARC files dominate the tail of the job. Use
`make test-emr LIMIT=<n>` to check throughput in your account before starting a
full run, and use the EMR console or Cost Explorer for current pricing.
