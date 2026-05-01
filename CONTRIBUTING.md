# Contributing to `cc-feeds`

This document contains information for developers who want to modify or extend `cc-feeds`.

## Development Setup

1. Follow the installation instructions in [README.md](README.md).
2. Install the package with development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

## Project Structure

- `cc_feeds/analysis/`: Core WARC response processing, HTML autodiscovery, feed parsing, and stats collection.
- `cc_feeds/emr/`: MapReduce job wiring, EMR launch/finalize helpers, and cluster-facing scripts.
- `cc_feeds/report/`: Report-time aggregation, quality scoring, and rendering.
- `cc_feeds/report/template.html`: Jinja2 template for the visual report.
- `cc_feeds/commoncrawl.py`: Common Crawl metadata and WARC path discovery.
- `cc_feeds/tranco.py`: Tranco list loading and caching.
- `cc_feeds/url.py`: URL normalization and domain extraction helpers.

## Code Standards

- **Formatting**: Use `black` and `isort`.
- **Typing**: Ensure code passes `mypy` checks.
- **Performance**: This tool is designed for high throughput. Avoid full-file reads; use streaming buffers and optimized parsers (`lxml`).

## Local Testing

Run the fast local checks before committing changes:

```bash
pytest
make typecheck
make lint
python -m cc_feeds.report.mock /tmp/cc-feeds-mock-report.html
```

`make test` runs a small local Common Crawl analysis and may need network access.
Use `make test-emr` for an end-to-end cloud smoke test after changes that affect
EMR packaging, WARC processing, or report finalization.

## Scaling to Distributed EMR

For large-scale analysis across the entire Common Crawl corpus:
- The tool is designed to be compatible with `mrjob`.
- See `cc_feeds/emr/` for the MapReduce and EMR wrapper code.
