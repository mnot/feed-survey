# Contributing to Web Feed Survey

This document contains information for developers who want to modify or extend `feed-survey`.

## Development Setup

1. Follow the installation instructions in [README.md](README.md).
2. Install the package with development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

## Project Structure

- `feed_survey/analysis/`: Core WARC response processing, HTML autodiscovery, feed parsing, and stats collection.
- `feed_survey/emr/`: MapReduce job wiring, EMR launch/finalize helpers, and cluster-facing scripts.
- `feed_survey/report/`: Report-time aggregation, quality scoring, and HTML/Markdown rendering.
- `feed_survey/report/template.html`: Jinja2 template for the visual report.
- `feed_survey/commoncrawl.py`: Common Crawl metadata and WARC path discovery.
- `feed_survey/tranco.py`: Tranco list loading and caching.
- `feed_survey/url.py`: URL normalization, host extraction, and registrable-site helpers.
- `tests/`: Unit tests and integration tests.
- `tests/fixtures/`: Small local fixtures and profiling helpers used by tests and smoke runs.
- `docs/`: Research notes and plans for future analysis dimensions.

## Code Standards

- **Formatting**: Use `black` and `isort`.
- **Typing**: Ensure code passes `mypy` checks.
- **Performance**: This tool is designed for high throughput. Avoid full-file reads; use streaming buffers and optimized parsers (`lxml`).

## Local Testing

Run the fast local checks before committing changes:

```bash
make test
make typecheck
make lint
make mock-report
```

`make check` runs all of the above. `make local-report` runs a small local
Common Crawl analysis and may need network access.
Use `make test-emr` for an end-to-end cloud smoke test after changes that affect
EMR packaging, WARC processing, or report finalization.
Use `feed-survey.mk` for local run configuration. The default `make` targets
load that file, and you can run with `CONFIG=/path/to/other.mk` when testing
another AWS account, bucket layout, crawl id, or EMR size.
Use `make report RESULTS_DIR=results/...` to re-render the HTML and Markdown
reports for an existing EMR result without rerunning the distributed job.
The HTML report is the visual artifact; the Markdown report should stay
plain, table-oriented, and explicit about denominators so it remains useful for
comparison and AI-assisted analysis.

## Scaling to Distributed EMR

For large-scale analysis across the entire Common Crawl corpus:
- The tool is designed to be compatible with `mrjob`.
- See `feed_survey/emr/` for the MapReduce and EMR wrapper code.
