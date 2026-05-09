PROJECT = feed_survey
CONFIG ?= feed-survey.mk
include feed-survey.defaults.mk
-include $(CONFIG)

PYTHON_TARGETS = feed_survey $(wildcard tests/*.py)

.PHONY: help
help:
	@echo "Common targets:"
	@echo "  make venv          Create or update the local development environment"
	@echo "  make test          Run fast unit tests"
	@echo "  make tidy          Format Python code"
	@echo "  make typecheck     Run mypy over package and tests"
	@echo "  make lint          Run pylint over package and tests"
	@echo "  make check         Run test, typecheck, lint, and mock report render"
	@echo "  make mock-report   Render synthetic HTML/Markdown reports at MOCK_REPORT"
	@echo "  make local-report  Run a one-WARC local analysis report"
	@echo "  make test-emr      Run an EMR smoke test"
	@echo "  make emr           Run the full EMR analysis"
	@echo "  make emr-timing EMR_LOG_CLUSTER_ID=j-...  Summarize preserved EMR timing logs"
	@echo "  make report RESULTS_DIR=results/...  Re-render saved EMR HTML/Markdown reports"
	@echo "  make wheels        Build EMR dependency wheels"
	@echo "  make upload-wheels Build and upload EMR dependency wheels"
	@echo "  make clean         Remove local generated scratch artifacts and venv"
	@echo ""
	@echo "Configuration:"
	@echo "  cp feed-survey.example.mk feed-survey.mk"
	@echo "  make CONFIG=/path/to/config.mk test-emr"

.PHONY: clean
clean: clean_py clean-local

.PHONY: clean-local
clean-local:
	rm -rf .pytest_cache .coverage htmlcov
	rm -f mock_report.html mock_report.md test_report.html test_report.md

.PHONY: lint
lint: lint_py

.PHONY: typecheck
typecheck: typecheck_py

.PHONY: tidy
tidy: tidy_py

.PHONY: test
test: test_py

.PHONY: check
check: test typecheck lint mock-report

.PHONY: local-report
local-report: venv
	PYTHONPATH=$(VENV) $(VENV)/python -m $(PROJECT).main --limit=1 --topn=$(LOCAL_TOP_N) --crawl-id=$(LOCAL_CRAWL_ID) --output=test_report.html

# Use := to ensure RUN_ID is fixed for the entire make execution
RUN_ID := $(shell date +%Y%m%d-%H%M%S)

MRJOB_BOOTSTRAP_ARGS = \
	--bootstrap "$(MRJOB_BOOTSTRAP_INSTALL)" \
	--bootstrap "aws s3 sync $(WHEEL_S3_PATH) /tmp/wheels/" \
	--bootstrap "$(MRJOB_BOOTSTRAP_PIP_INSTALL)"

.PHONY: check-s3-config
check-s3-config:
	@test -n "$(OUTPUT_DIR)" || (echo "Set OUTPUT_DIR in $(CONFIG) or pass CONFIG=/path/to/config.mk"; exit 1)
	@test -n "$(PATHS_PREFIX)" || (echo "Set PATHS_PREFIX in $(CONFIG) or pass CONFIG=/path/to/config.mk"; exit 1)
	@test -n "$(WHEEL_S3_PATH)" || (echo "Set WHEEL_S3_PATH in $(CONFIG) or pass CONFIG=/path/to/config.mk"; exit 1)
	@case "$(OUTPUT_DIR) $(PATHS_PREFIX) $(WHEEL_S3_PATH)" in *YOUR-BUCKET*) echo "Replace YOUR-BUCKET in $(CONFIG) before running EMR targets"; exit 1;; esac

.PHONY: tranco-cache
tranco-cache: venv
	FEED_SURVEY_CACHE_DIR="$(TRANCO_CACHE_DIR)" FEED_SURVEY_TRANCO_LIST="$(TRANCO_LIST)" $(VENV)/python -c "from feed_survey.tranco import ensure_tranco_cache; ensure_tranco_cache()"

.PHONY: emr
emr: venv tranco-cache check-s3-config
	$(VENV)/python -m feed_survey.emr.split_paths \
		s3://commoncrawl/crawl-data/$(CRAWL_ID)/warc.paths.gz \
		$(PATHS_PREFIX)$(CRAWL_ID)-$(RUN_ID)/ \
		$(MAP_TASKS)
	$(VENV)/python -m feed_survey.emr.job -r emr -c $(MRJOB_CONFIG) \
		$(MRJOB_BOOTSTRAP_ARGS) \
		--files "$(TRANCO_CACHE)#top-1m-sites.csv" \
		--cleanup $(MRJOB_CLEANUP) \
		$(PATHS_PREFIX)$(CRAWL_ID)-$(RUN_ID)/ \
		--output-dir $(OUTPUT_DIR)$(CRAWL_ID)-$(RUN_ID)/ \
		--no-read-logs --no-cat-output \
		--jobconf mapreduce.job.reduces=$(REDUCES) \
		--topn $(TOP_N) \
		--tranco-list $(TRANCO_LIST)
	mkdir -p results/$(CRAWL_ID)-$(RUN_ID)
	aws s3 sync $(OUTPUT_DIR)$(CRAWL_ID)-$(RUN_ID)/ results/$(CRAWL_ID)-$(RUN_ID)/
	$(VENV)/python -m feed_survey.emr.finalize results/$(CRAWL_ID)-$(RUN_ID)/ $(CRAWL_ID) results/$(CRAWL_ID)-$(RUN_ID)/report.html
	@echo "Reports generated at results/$(CRAWL_ID)-$(RUN_ID)/report.html and results/$(CRAWL_ID)-$(RUN_ID)/report.md"

MOCK_REPORT ?= mock_report.html
RESULTS_DIR ?=

.PHONY: wheels
wheels:
	mkdir -p wheels
	docker run --rm --platform linux/amd64 -v $(PWD)/wheels:/output amazonlinux:2023 /bin/bash -c "\
		yum install -y gcc gcc-c++ python3.12-devel python3.12-pip libxml2-devel libxslt-devel zlib-devel lz4-devel brotli-devel && \
		/usr/bin/python3.12 -m pip wheel --wheel-dir=/output mrjob fastwarc beautifulsoup4 lxml python-dateutil requests boto3 publicsuffix2"

.PHONY: mock-report mock_report
mock-report mock_report: venv
	$(VENV)/python -m feed_survey.report.mock $(MOCK_REPORT)
	@echo "Report generated at $(MOCK_REPORT) with Markdown sibling"

.PHONY: upload-wheels
upload-wheels: wheels check-s3-config
	aws s3 sync wheels/ $(WHEEL_S3_PATH)

LIMIT ?= 1

.PHONY: test-emr
test-emr: venv tranco-cache check-s3-config
	$(VENV)/python -m feed_survey.emr.split_paths \
		tests/fixtures/warc.paths.txt \
		$(PATHS_PREFIX)test-$(RUN_ID)/ \
		$(TEST_MAP_TASKS) \
		$(LIMIT)
	$(VENV)/python -m feed_survey.emr.job -r emr -c $(MRJOB_TEST_CONFIG) \
		$(MRJOB_BOOTSTRAP_ARGS) \
		--files "$(TRANCO_CACHE)#top-1m-sites.csv" \
		--cleanup $(MRJOB_CLEANUP) \
		--no-read-logs --no-cat-output \
		--jobconf mapreduce.job.reduces=$(TEST_REDUCES) \
		--output-dir $(OUTPUT_DIR)test-$(RUN_ID)/ \
		--limit $(LIMIT) \
		--topn $(TOP_N) \
		--tranco-list $(TRANCO_LIST) \
		$(PATHS_PREFIX)test-$(RUN_ID)/
	mkdir -p results/test-$(RUN_ID)
	aws s3 sync $(OUTPUT_DIR)test-$(RUN_ID)/ results/test-$(RUN_ID)/
	$(VENV)/python -m feed_survey.emr.finalize results/test-$(RUN_ID)/ $(CRAWL_ID) results/test-$(RUN_ID)/report.html
	@echo "Reports generated at results/test-$(RUN_ID)/report.html and results/test-$(RUN_ID)/report.md"

# Update a specific report: make results/test-xxx/report.html
.PHONY: results/%/report.html
results/%/report.html: venv
	$(VENV)/python -m feed_survey.emr.finalize results/$*/ $(CRAWL_ID) $@

.PHONY: report
report: venv
	@test -n "$(RESULTS_DIR)" || (echo "Usage: make report RESULTS_DIR=results/test-YYYYMMDD-HHMMSS" && exit 1)
	$(VENV)/python -m feed_survey.emr.finalize $(RESULTS_DIR) $(CRAWL_ID) $(RESULTS_DIR)/report.html
	@echo "Reports generated at $(RESULTS_DIR)/report.html and $(RESULTS_DIR)/report.md"

.PHONY: emr-timing
emr-timing: venv
	@test -n "$(EMR_LOG_CLUSTER_ID)" || (echo "Usage: make emr-timing EMR_LOG_CLUSTER_ID=j-..." && exit 1)
	$(VENV)/python -m feed_survey.emr.timing --cluster-id $(EMR_LOG_CLUSTER_ID) --log-dir $(EMR_LOG_DIR)

include Makefile.pyproject
