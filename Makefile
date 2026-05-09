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
	@echo "  make show-config   Print effective make configuration"
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
FULL_RUN_NAME = $(CRAWL_ID)-$(RUN_ID)
TEST_RUN_NAME = test-$(RUN_ID)

MRJOB_BOOTSTRAP_ARGS = \
	--bootstrap "$(MRJOB_BOOTSTRAP_INSTALL)" \
	--bootstrap "aws s3 sync $(WHEEL_S3_PATH) /tmp/wheels/" \
	--bootstrap "$(MRJOB_BOOTSTRAP_PIP_INSTALL)"

MRJOB_COMMON_ARGS = \
	-r emr \
	$(MRJOB_BOOTSTRAP_ARGS) \
	--files "$(TRANCO_CACHE)\#top-1m-sites.csv" \
	--cleanup $(MRJOB_CLEANUP) \
	--no-read-logs --no-cat-output \
	--topn $(TOP_N) \
	--tranco-list $(TRANCO_LIST)

.PHONY: show-config
show-config:
	@echo "CONFIG=$(CONFIG)"
	@echo "CRAWL_ID=$(CRAWL_ID)"
	@echo "LOCAL_CRAWL_ID=$(LOCAL_CRAWL_ID)"
	@echo "TOP_N=$(TOP_N)"
	@echo "LOCAL_TOP_N=$(LOCAL_TOP_N)"
	@echo "TRANCO_LIST=$(TRANCO_LIST)"
	@echo "TRANCO_CACHE=$(TRANCO_CACHE)"
	@echo "OUTPUT_DIR=$(OUTPUT_DIR)"
	@echo "PATHS_PREFIX=$(PATHS_PREFIX)"
	@echo "WHEEL_S3_PATH=$(WHEEL_S3_PATH)"
	@echo "MAP_TASKS=$(MAP_TASKS)"
	@echo "REDUCES=$(REDUCES)"
	@echo "TEST_MAP_TASKS=$(TEST_MAP_TASKS)"
	@echo "TEST_REDUCES=$(TEST_REDUCES)"
	@echo "MRJOB_CONFIG=$(MRJOB_CONFIG)"
	@echo "MRJOB_TEST_CONFIG=$(MRJOB_TEST_CONFIG)"
	@echo "MRJOB_CLEANUP=$(MRJOB_CLEANUP)"
	@echo "EMR_LOG_DIR=$(EMR_LOG_DIR)"

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
emr: check-s3-config venv tranco-cache
	$(VENV)/python -m feed_survey.emr.split_paths \
		s3://commoncrawl/crawl-data/$(CRAWL_ID)/warc.paths.gz \
		$(PATHS_PREFIX)$(FULL_RUN_NAME)/ \
		$(MAP_TASKS)
	$(VENV)/python -m feed_survey.emr.job -c $(MRJOB_CONFIG) \
		$(MRJOB_COMMON_ARGS) \
		--jobconf mapreduce.job.reduces=$(REDUCES) \
		--output-dir $(OUTPUT_DIR)$(FULL_RUN_NAME)/ \
		$(PATHS_PREFIX)$(FULL_RUN_NAME)/
	mkdir -p results/$(FULL_RUN_NAME)
	aws s3 sync $(OUTPUT_DIR)$(FULL_RUN_NAME)/ results/$(FULL_RUN_NAME)/
	$(VENV)/python -m feed_survey.emr.finalize results/$(FULL_RUN_NAME)/ $(CRAWL_ID) results/$(FULL_RUN_NAME)/report.html
	@echo "Reports generated at results/$(FULL_RUN_NAME)/report.html and results/$(FULL_RUN_NAME)/report.md"

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
upload-wheels: check-s3-config wheels
	aws s3 sync wheels/ $(WHEEL_S3_PATH)

LIMIT ?= 1

.PHONY: test-emr
test-emr: check-s3-config venv tranco-cache
	$(VENV)/python -m feed_survey.emr.split_paths \
		tests/fixtures/warc.paths.txt \
		$(PATHS_PREFIX)$(TEST_RUN_NAME)/ \
		$(TEST_MAP_TASKS) \
		$(LIMIT)
	$(VENV)/python -m feed_survey.emr.job -c $(MRJOB_TEST_CONFIG) \
		$(MRJOB_COMMON_ARGS) \
		--jobconf mapreduce.job.reduces=$(TEST_REDUCES) \
		--output-dir $(OUTPUT_DIR)$(TEST_RUN_NAME)/ \
		--limit $(LIMIT) \
		$(PATHS_PREFIX)$(TEST_RUN_NAME)/
	mkdir -p results/$(TEST_RUN_NAME)
	aws s3 sync $(OUTPUT_DIR)$(TEST_RUN_NAME)/ results/$(TEST_RUN_NAME)/
	$(VENV)/python -m feed_survey.emr.finalize results/$(TEST_RUN_NAME)/ $(CRAWL_ID) results/$(TEST_RUN_NAME)/report.html
	@echo "Reports generated at results/$(TEST_RUN_NAME)/report.html and results/$(TEST_RUN_NAME)/report.md"

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
