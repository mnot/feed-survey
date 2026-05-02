import os
import zipfile
from typing import Optional, Set

from cc_feeds.download import CACHE_DIR, download_file

TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"


def get_tranco_list(top_n: Optional[int] = None) -> Set[str]:
    """Download, unzip and return the Tranco top list as a set of domains."""
    local_csv = "top-1m.csv"
    test_csv = "tests/fixtures/top-1m.csv"
    if os.path.exists(local_csv):
        csv_path = local_csv
    elif os.path.exists(test_csv):
        csv_path = test_csv
    else:
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
