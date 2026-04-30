PROJECT = cc_feeds


.PHONY: clean
clean: clean_py

.PHONY: lint
lint: lint_py

.PHONY: typecheck
typecheck: typecheck_py
	PYTHONPATH=. $(VENV)/python -m mypy *.py

.PHONY: tidy
tidy: tidy_py

.PHONY: test
test: venv
	PYTHONPATH=$(VENV) $(VENV)/python -m $(PROJECT).main --limit=1 --topn=1000 --crawl-id=CC-MAIN-2024-18 --output=test_report.html

CRAWL_ID ?= CC-MAIN-2026-12
OUTPUT_DIR = s3://mnot-cc-feeds/
PATHS_PREFIX = s3://mnot-cc-feeds/paths/
# Use := to ensure RUN_ID is fixed for the entire make execution
RUN_ID := $(shell date +%Y%m%d-%H%M%S)

MAP_TASKS ?= 400
TEST_MAP_TASKS ?= 20

.PHONY: emr
emr: venv
	$(VENV)/python split_paths.py \
		s3://commoncrawl/crawl-data/$(CRAWL_ID)/warc.paths.gz \
		$(PATHS_PREFIX)$(CRAWL_ID)-$(RUN_ID)/ \
		$(MAP_TASKS)
	$(VENV)/python mr_job.py -r emr -c mrjob.conf \
		$(PATHS_PREFIX)$(CRAWL_ID)-$(RUN_ID)/ \
		--output-dir $(OUTPUT_DIR)$(CRAWL_ID)-$(RUN_ID)/ \
		--no-read-logs --no-cat-output \
		--jobconf mapreduce.job.reduces=20 \
		--topn 500000
	mkdir -p results/$(CRAWL_ID)-$(RUN_ID)
	aws s3 sync $(OUTPUT_DIR)$(CRAWL_ID)-$(RUN_ID)/ results/$(CRAWL_ID)-$(RUN_ID)/
	$(VENV)/python finalize.py results/$(CRAWL_ID)-$(RUN_ID)/ $(CRAWL_ID) results/$(CRAWL_ID)-$(RUN_ID)/report.html
	@echo "Report generated at results/$(CRAWL_ID)-$(RUN_ID)/report.html"

WHEEL_S3_PATH = s3://mnot-cc-feeds/wheels/

.PHONY: wheels
wheels:
	mkdir -p wheels
	docker run --rm --platform linux/amd64 -v $(PWD)/wheels:/output amazonlinux:2023 /bin/bash -c "\
		yum install -y gcc gcc-c++ python3.12-devel python3.12-pip libxml2-devel libxslt-devel zlib-devel lz4-devel brotli-devel && \
		/usr/bin/python3.12 -m pip wheel --wheel-dir=/output mrjob fastwarc beautifulsoup4 lxml python-dateutil requests boto3"

.PHONY: mock_report
mock_report: venv
	$(VENV)/python mock_report.py mock_report.html
	open mock_report.html

.PHONY: upload-wheels
upload-wheels: wheels
	aws s3 sync wheels/ $(WHEEL_S3_PATH)

LIMIT ?= 50

TEST_CLUSTER_FILE = TEST_CLUSTER

.PHONY: test-emr
test-emr: venv
	$(VENV)/python split_paths.py \
		test/warc.paths.txt \
		$(PATHS_PREFIX)test-$(RUN_ID)/ \
		$(TEST_MAP_TASKS)
	@if [ ! -s $(TEST_CLUSTER_FILE) ]; then \
		echo "Starting new persistent cluster..."; \
		$(VENV)/python mrjob_wrapper.py mrjob.tools.emr.create_cluster -c mrjob.conf 2>&1 | tee cluster_start.log; \
		grep -o "j-[A-Z0-9]*" cluster_start.log | head -n 1 > $(TEST_CLUSTER_FILE); \
		rm cluster_start.log; \
	fi; \
	CLUSTER_ID=$$(cat $(TEST_CLUSTER_FILE)); \
	if [ -z "$$CLUSTER_ID" ]; then \
		echo "ERROR: Failed to start cluster or find cluster ID in cluster_start.log"; \
		exit 1; \
	fi; \
	echo "Using cluster $$CLUSTER_ID"; \
	$(VENV)/python mr_job.py -r emr --cluster-id $$CLUSTER_ID -c mrjob.conf \
		--no-read-logs --no-cat-output \
		--jobconf mapreduce.job.reduces=20 \
		--output-dir $(OUTPUT_DIR)test-$(RUN_ID)/ \
		--limit $(LIMIT) \
		--topn 500000 \
		$(PATHS_PREFIX)test-$(RUN_ID)/
	mkdir -p results/test-$(RUN_ID)
	aws s3 sync $(OUTPUT_DIR)test-$(RUN_ID)/ results/test-$(RUN_ID)/
	$(VENV)/python finalize.py results/test-$(RUN_ID)/ $(CRAWL_ID) results/test-$(RUN_ID)/report.html
	@echo "Report generated at results/test-$(RUN_ID)/report.html"
	@echo ""
	@echo "**************************************************"
	@echo "* CLUSTER STILL RUNNING - make test-clean IF DONE *"
	@echo "**************************************************"

.PHONY: test-clean
test-clean:
	@if [ -f $(TEST_CLUSTER_FILE) ]; then \
		CLUSTER_ID=$$(cat $(TEST_CLUSTER_FILE)); \
		echo "Terminating cluster $$CLUSTER_ID..."; \
		$(VENV)/python mrjob_wrapper.py mrjob.tools.emr.terminate_cluster $$CLUSTER_ID || true; \
		rm $(TEST_CLUSTER_FILE); \
		echo "Cleaned up."; \
	else \
		echo "No persistent cluster found."; \
	fi

# Update a specific report: make results/test-xxx/report.html
.PHONY: results/%/report.html
results/%/report.html: venv
	$(VENV)/python finalize.py results/$*/ $(CRAWL_ID) $@

include Makefile.pyproject
