PROJECT = cc_feeds


.PHONY: clean
clean: clean_py

.PHONY: lint
lint: lint_py

.PHONY: typecheck
typecheck: typecheck_py

.PHONY: tidy
tidy: tidy_py

.PHONY: test
test: venv
	PYTHONPATH=$(VENV) $(VENV)/python -m $(PROJECT).main --limit=1 --topn=1000 --crawl-id=CC-MAIN-2024-18 --output=test_report.html

CRAWL_ID = CC-MAIN-2026-12
OUTPUT_DIR = s3://mnot-cc-feeds/
# Use := to ensure RUN_ID is fixed for the entire make execution
RUN_ID := $(shell date +%Y%m%d-%H%M%S)

.PHONY: emr
emr: venv
	$(VENV)/python mr_job.py -r emr -c mrjob.conf \
		s3://commoncrawl/crawl-data/$(CRAWL_ID)/warc.paths.gz \
		--output-dir $(OUTPUT_DIR)$(CRAWL_ID)-$(RUN_ID)/ \
		--topn 500000
	mkdir -p results/$(CRAWL_ID)-$(RUN_ID)
	aws s3 sync $(OUTPUT_DIR)$(CRAWL_ID)-$(RUN_ID)/ results/$(CRAWL_ID)-$(RUN_ID)/

.PHONY: test-emr
test-emr: venv
	$(VENV)/python mr_job.py -r emr -c mrjob.conf \
		--output-dir $(OUTPUT_DIR)test-$(RUN_ID)/ \
		s3://mnot-cc-feeds/smoke_test.txt
	mkdir -p results/test-$(RUN_ID)
	aws s3 sync $(OUTPUT_DIR)test-$(RUN_ID)/ results/test-$(RUN_ID)/

include Makefile.pyproject
