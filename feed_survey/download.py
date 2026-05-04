import os

import requests
from tqdm import tqdm

CACHE_DIR = os.path.expanduser(
    os.environ.get("FEED_SURVEY_CACHE_DIR", "~/.cache/feed-survey")
)


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
