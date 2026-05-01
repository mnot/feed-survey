# Contributing to `cc-feeds`

This document contains information for developers who want to modify or extend `cc-feeds`.

## Development Setup

1. Follow the installation instructions in [README.md](README.md).
2. Install development dependencies:
   ```bash
   pip install pytest black isort mypy
   ```

## Project Structure

- `cc_feeds/main.py`: CLI orchestration and WARC streaming logic.
- `cc_feeds/processor.py`: Core logic for HTML parsing and feed validation.
- `cc_feeds/report.py`: Data aggregation and histogram generation.
- `cc_feeds/report_template.html`: Jinja2 template for the visual report.
- `cc_feeds/utils.py`: Helpers for Tranco list caching and CC API interaction.

## Code Standards

- **Formatting**: Use `black` and `isort`.
- **Typing**: Ensure code passes `mypy` checks.
- **Performance**: This tool is designed for high throughput. Avoid full-file reads; use streaming buffers and optimized parsers (`lxml`).

## Local Testing

You can run local tests using small record limits to verify changes to the reporting or parsing logic:

```bash
cc-feeds --limit 1 --limit-records 1000 --output test_report.html
```

## Scaling to Distributed EMR

For large-scale analysis across the entire Common Crawl corpus:
- The tool is designed to be compatible with `mrjob`.
- See `cc_feeds/mr_job.py` for the MapReduce wrapper.
