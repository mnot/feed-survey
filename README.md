# Common Crawl Feed Analysis (`cc-feeds`)

A high-performance, distributed tool to analyze the prevalence and quality of RSS/Atom feeds within the Common Crawl dataset using AWS EMR.

## Overview

`cc-feeds` leverages MapReduce to process the massive Common Crawl corpus (approx. 90,000 WARC files) in parallel. It extracts autodiscovery links, validates discovered feeds, and generates granular JSON-lines reports.

## Key Features

- **Distributed MapReduce**: Built on `mrjob` for seamless scaling from a few instances to hundreds of nodes on AWS EMR.
- **Python 3.12 Optimized**: Uses modern Python syntax and efficient libraries (`fastwarc`, `lxml`) for maximum throughput.
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
# Clone and setup virtual environment
git clone https://github.com/mnot/cc-feeds.git
cd cc-feeds
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Local Usage
You can run the analysis on your own machine for debugging. This uses the `local` runner and doesn't require AWS.

```bash
# Process a local list of WARC paths
cc-feeds-job -r local tiny_input.txt --output-dir ./local-results/
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
- **`TargetSpotCapacity`**: Set to `100` for a ~15 hour run, or `200` for ~7.5 hours.
- **`instance_fleets`**: Defines the mix of Spot instances (m5, r5, c5) to ensure high availability.

### `Makefile`
- **`CRAWL_ID`**: The Common Crawl index to process (e.g., `CC-MAIN-2026-12`).
- **`OUTPUT_DIR`**: The S3 bucket where results and logs will be stored.

## Project Structure

- `mr_job.py`: The MapReduce entry point and orchestration logic.
- `cc_feeds/processor.py`: Core logic for parsing WARC records and extracting feed metadata.
- `cc_feeds/utils.py`: Utility functions for Tranco list management and S3 streaming.
- `mrjob.conf`: EMR orchestration settings (Python 3.12, dependencies, instance fleets).
- `.mrjobignore`: Prevents local virtual environments and caches from being uploaded to workers.

## Local Development & Testing

You can run the processing logic locally for debugging without launching a cluster:
```bash
# Process a single WARC file locally
PYTHONPATH=. .venv/bin/python mr_job.py local tiny_input.txt --output-dir ./local-results/
```

## Cost Estimation (AWS USD)
- **100 Nodes (400 mappers)**: ~$150 USD total (~15 hours).
- **200 Nodes (800 mappers)**: ~$150 USD total (~7.5 hours).
*Note: Total cost is similar because the total compute work is identical; higher node counts simply finish the work faster.*
