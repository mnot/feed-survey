import os
import zipfile
from typing import Optional, Set

from feed_survey.download import CACHE_DIR, download_file

TRANCO_STANDARD_URL = "https://tranco-list.eu/top-1m.csv.zip"
TRANCO_SUBDOMAINS_URL = "https://tranco-list.eu/top-1m-incl-subdomains.csv.zip"
TRANCO_STANDARD_CSV = "top-1m.csv"
TRANCO_SUBDOMAINS_CSV = "top-1m-incl-subdomains.csv"


def tranco_includes_subdomains(value: Optional[bool] = None) -> bool:
    if value is not None:
        return value
    env_value = os.environ.get("FEED_SURVEY_TRANCO_LIST", "subdomains")
    return env_value.strip().lower() not in {"0", "false", "no", "standard"}


def tranco_cache_name(include_subdomains: Optional[bool] = None) -> str:
    return (
        TRANCO_SUBDOMAINS_CSV
        if tranco_includes_subdomains(include_subdomains)
        else TRANCO_STANDARD_CSV
    )


def get_tranco_list(
    top_n: Optional[int] = None, include_subdomains: Optional[bool] = None
) -> Set[str]:
    """Download, unzip and return the selected Tranco top list as a set."""
    include = tranco_includes_subdomains(include_subdomains)
    cache_name = tranco_cache_name(include)
    local_csv = TRANCO_STANDARD_CSV
    test_csv = os.path.join("tests", "fixtures", cache_name)
    if os.path.exists(local_csv):
        csv_path = local_csv
    elif os.path.exists(test_csv):
        csv_path = test_csv
    else:
        os.makedirs(CACHE_DIR, exist_ok=True)
        zip_path = os.path.join(CACHE_DIR, f"{cache_name}.zip")
        csv_path = os.path.join(CACHE_DIR, cache_name)

        if not os.path.exists(csv_path):
            print(f"Downloading Tranco list ({tranco_list_label(include)})...")
            download_file(_tranco_url(include), zip_path)
            print("Unzipping Tranco list...")
            extract_tranco_csv(zip_path, csv_path)

    domains = []
    with open(csv_path, "r", encoding="utf-8") as f_in:
        for idx, line in enumerate(f_in):
            if top_n and idx >= top_n:
                break
            parts = line.strip().split(",")
            if len(parts) == 2:
                domains.append(parts[1])
    return set(domains)


def tranco_list_label(include_subdomains: Optional[bool] = None) -> str:
    return (
        "subdomain-inclusive"
        if tranco_includes_subdomains(include_subdomains)
        else "standard domain-only"
    )


def _tranco_url(include_subdomains: bool) -> str:
    return TRANCO_SUBDOMAINS_URL if include_subdomains else TRANCO_STANDARD_URL


def extract_tranco_csv(zip_path: str, csv_path: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        csv_members = [
            name
            for name in zip_ref.namelist()
            if not name.endswith("/") and name.lower().endswith(".csv")
        ]
        if not csv_members:
            raise FileNotFoundError("Tranco archive did not contain a CSV file")
        with (
            zip_ref.open(csv_members[0], "r") as src,
            open(csv_path, "wb") as dest,
        ):
            dest.write(src.read())
