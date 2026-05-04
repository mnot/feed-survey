import gzip
import os
from typing import List, cast

import requests

from feed_survey.download import CACHE_DIR, download_file


def get_latest_crawl_id() -> str:
    """Find the latest crawl ID from Common Crawl's index API."""
    url = "https://index.commoncrawl.org/collinfo.json"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data:
        raise RuntimeError("Could not find any crawls in collinfo.json")
    return cast(str, data[0]["id"])


def get_warc_paths(crawl_id: str) -> List[str]:
    """Download and return the list of WARC paths for a given crawl."""
    warc_paths_url = f"https://data.commoncrawl.org/crawl-data/{crawl_id}/warc.paths.gz"
    local_path = os.path.join(CACHE_DIR, f"{crawl_id}-warc.paths.gz")

    if not os.path.exists(local_path):
        print(f"Downloading WARC paths for {crawl_id}...")
        download_file(warc_paths_url, local_path)

    with gzip.open(local_path, "rt") as f_in:
        return [line.strip() for line in f_in]
