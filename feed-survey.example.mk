# Example local run configuration for Web Feed Survey.
#
# Copy this file to feed-survey.mk, then edit bucket paths and sizing for your
# AWS account. Alternatively, pass CONFIG=/path/to/another.mk to make.

CRAWL_ID ?= CC-MAIN-2026-12
LOCAL_CRAWL_ID ?= CC-MAIN-2024-18
TOP_N ?= 500000
LOCAL_TOP_N ?= 1000
# TOP_N is applied to registrable sites after Public Suffix List normalization.
# Hosted sub-sites on private suffixes, such as *.blogspot.com or *.github.io,
# are scoped independently when the Public Suffix List says they are sites.

OUTPUT_DIR = s3://YOUR-BUCKET/feed-survey/results/
PATHS_PREFIX = s3://YOUR-BUCKET/feed-survey/paths/
WHEEL_S3_PATH = s3://YOUR-BUCKET/feed-survey/wheels/

MAP_TASKS ?= 1600
REDUCES ?= 20
TEST_MAP_TASKS ?= 20
TEST_REDUCES ?= 1

MRJOB_CONFIG ?= mrjob.conf
MRJOB_TEST_CONFIG ?= mrjob-test.conf
MRJOB_BOOTSTRAP_INSTALL ?= sudo dnf install -y python3.12 python3.12-pip libxml2 libxslt zlib lz4 brotli
MRJOB_BOOTSTRAP_PIP_INSTALL ?= sudo /usr/bin/python3.12 -m pip install --no-index --find-links=/tmp/wheels/ mrjob fastwarc beautifulsoup4 lxml python-dateutil requests boto3 publicsuffix2
MRJOB_CLEANUP ?= TMP
EMR_LOG_DIR ?= /tmp/feed-survey-emr-logs
EMR_LOG_CLUSTER_ID ?=

TRANCO_CACHE_DIR ?= $(HOME)/.cache/feed-survey
TRANCO_LIST ?= subdomains
ifeq ($(TRANCO_LIST),standard)
TRANCO_CACHE_BASENAME ?= top-1m-sites.csv
else
TRANCO_CACHE_BASENAME ?= top-1m-incl-subdomains-sites.csv
endif
TRANCO_CACHE ?= $(TRANCO_CACHE_DIR)/$(TRANCO_CACHE_BASENAME)
