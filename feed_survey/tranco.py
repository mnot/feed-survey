import os
import zipfile
from typing import Optional, Set

from feed_survey.download import CACHE_DIR, download_file
from feed_survey.url import get_site

TRANCO_STANDARD_URL = "https://tranco-list.eu/top-1m.csv.zip"
TRANCO_SUBDOMAINS_URL = "https://tranco-list.eu/top-1m-incl-subdomains.csv.zip"
TRANCO_STANDARD_CSV = "top-1m.csv"
TRANCO_SUBDOMAINS_CSV = "top-1m-incl-subdomains.csv"
TRANCO_STANDARD_SITES_CSV = "top-1m-sites.csv"
TRANCO_SUBDOMAINS_SITES_CSV = "top-1m-incl-subdomains-sites.csv"


def tranco_includes_subdomains(value: Optional[bool] = None) -> bool:
    if value is not None:
        return value
    env_value = os.environ.get("FEED_SURVEY_TRANCO_LIST", "subdomains")
    return env_value.strip().lower() not in {"0", "false", "no", "standard"}


def tranco_cache_name(
    include_subdomains: Optional[bool] = None, normalized: bool = True
) -> str:
    include = tranco_includes_subdomains(include_subdomains)
    if normalized:
        return TRANCO_SUBDOMAINS_SITES_CSV if include else TRANCO_STANDARD_SITES_CSV
    return TRANCO_SUBDOMAINS_CSV if include else TRANCO_STANDARD_CSV


def get_tranco_list(
    top_n: Optional[int] = None, include_subdomains: Optional[bool] = None
) -> Set[str]:
    """Download, unzip and return the selected Tranco top list as a set."""
    include = tranco_includes_subdomains(include_subdomains)
    csv_path, normalized = _find_tranco_csv(include)

    sites = []
    with open(csv_path, "r", encoding="utf-8") as f_in:
        for idx, line in enumerate(f_in):
            if top_n and idx >= top_n:
                break
            parts = line.strip().split(",")
            if len(parts) == 2:
                site = parts[1] if normalized else get_site(parts[1])
                if site:
                    sites.append(site)
    return set(sites)


def ensure_tranco_cache(include_subdomains: Optional[bool] = None) -> str:
    """Return a local Tranco CSV normalized to registrable sites."""
    include = tranco_includes_subdomains(include_subdomains)
    os.makedirs(CACHE_DIR, exist_ok=True)
    raw_path = _ensure_raw_tranco_csv(include)
    normalized_path = os.path.join(CACHE_DIR, tranco_cache_name(include))

    if (
        not os.path.exists(normalized_path)
        or os.path.getmtime(normalized_path) < os.path.getmtime(raw_path)
        or _line_count(normalized_path) != _line_count(raw_path)
    ):
        print(f"Normalizing Tranco list ({tranco_list_label(include)})...")
        _write_normalized_sites(raw_path, normalized_path)
    return normalized_path


def tranco_list_label(include_subdomains: Optional[bool] = None) -> str:
    return (
        "subdomain-inclusive"
        if tranco_includes_subdomains(include_subdomains)
        else "standard domain-only"
    )


def _tranco_url(include_subdomains: bool) -> str:
    return TRANCO_SUBDOMAINS_URL if include_subdomains else TRANCO_STANDARD_URL


def _find_tranco_csv(include_subdomains: bool) -> tuple[str, bool]:
    normalized_name = tranco_cache_name(include_subdomains)
    raw_name = tranco_cache_name(include_subdomains, normalized=False)

    for candidate in (
        TRANCO_STANDARD_SITES_CSV,
        os.path.join("tests", "fixtures", normalized_name),
        os.path.join(CACHE_DIR, normalized_name),
    ):
        if os.path.exists(candidate):
            return candidate, True

    for candidate in (
        TRANCO_STANDARD_CSV,
        os.path.join("tests", "fixtures", raw_name),
        os.path.join(CACHE_DIR, raw_name),
    ):
        if os.path.exists(candidate):
            return candidate, False

    return ensure_tranco_cache(include_subdomains), True


def _ensure_raw_tranco_csv(include_subdomains: bool) -> str:
    raw_name = tranco_cache_name(include_subdomains, normalized=False)
    raw_path = os.path.join(CACHE_DIR, raw_name)
    if os.path.exists(raw_path):
        return raw_path

    zip_path = os.path.join(CACHE_DIR, f"{raw_name}.zip")
    print(f"Downloading Tranco list ({tranco_list_label(include_subdomains)})...")
    download_file(_tranco_url(include_subdomains), zip_path)
    print("Unzipping Tranco list...")
    extract_tranco_csv(zip_path, raw_path)
    return raw_path


def _write_normalized_sites(raw_path: str, normalized_path: str) -> None:
    with (
        open(raw_path, "r", encoding="utf-8") as raw_file,
        open(normalized_path, "w", encoding="utf-8") as normalized_file,
    ):
        for line in raw_file:
            parts = line.strip().split(",")
            if len(parts) != 2:
                normalized_file.write(line)
                continue
            site = get_site(parts[1])
            normalized_file.write(f"{parts[0]},{site}\n")


def _line_count(path: str) -> int:
    with open(path, "rb") as count_file:
        return sum(1 for _ in count_file)


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
