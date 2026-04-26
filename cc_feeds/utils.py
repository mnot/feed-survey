import gzip
import os
import zipfile
from typing import List, Optional, Set, cast
from urllib.parse import urlparse, urlunparse

import requests
from tqdm import tqdm

TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
CACHE_DIR = os.path.expanduser("~/.cache/cc-feeds")


def normalize_url(url: str) -> str:
    """Normalize URL to help matching between autodiscovery and processing."""
    try:
        parsed = urlparse(url)
        # Lowercase netloc, remove fragments, remove trailing slash from path
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"
        return urlunparse(
            (parsed.scheme, parsed.netloc.lower(), path, "", parsed.query, "")
        )
    except Exception:  # pylint: disable=broad-except
        return url


def download_file(url: str, dest_path: str) -> None:
    """Download a file with a progress bar."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    total_size = int(response.headers.get("content-length", 0))

    with (
        open(dest_path, "wb") as f_out,
        tqdm(
            desc=os.path.basename(dest_path),
            total=total_size,
            unit="iB",
            unit_scale=True,
            unit_divisor=1024,
        ) as progress_bar,
    ):
        for data in response.iter_content(chunk_size=1024):
            written = f_out.write(data)
            progress_bar.update(written)


def get_tranco_list(top_n: Optional[int] = None) -> Set[str]:
    """Download, unzip and return the Tranco top list as a set of domains."""
    # Check if the file was uploaded by mrjob to the current working directory
    local_csv = "top-1m.csv"
    if os.path.exists(local_csv):
        csv_path = local_csv
    else:
        # Fallback to cache directory (local development)
        os.makedirs(CACHE_DIR, exist_ok=True)
        zip_path = os.path.join(CACHE_DIR, "tranco.zip")
        csv_path = os.path.join(CACHE_DIR, "top-1m.csv")

        if not os.path.exists(csv_path):
            print("Downloading Tranco list...")
            download_file(TRANCO_URL, zip_path)
            print("Unzipping Tranco list...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(CACHE_DIR)

    domains = []
    with open(csv_path, "r", encoding="utf-8") as f_in:
        for idx, line in enumerate(f_in):
            if top_n and idx >= top_n:
                break
            parts = line.strip().split(",")
            if len(parts) == 2:
                domains.append(parts[1])
    return set(domains)


def get_domain(url: str) -> str:
    """Fast extraction of domain from URL."""
    try:
        if "://" in url:
            # Skip scheme and take netloc
            netloc = (
                url.split("://", 1)[1]
                .split("/", 1)[0]
                .split("?", 1)[0]
                .split("#", 1)[0]
            )
            if ":" in netloc:  # Remove port
                return netloc.split(":", 1)[0]
            return netloc
        return url.split("/", 1)[0]
    except Exception:
        return ""


def get_latest_crawl_id() -> str:
    """Find the latest crawl ID from Common Crawl's index API."""
    url = "https://index.commoncrawl.org/collinfo.json"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data:
        raise RuntimeError("Could not find any crawls in collinfo.json")
    # The first one is usually the latest
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
