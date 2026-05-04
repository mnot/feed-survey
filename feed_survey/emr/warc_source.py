"""WARC input helpers for EMR jobs."""

# pylint: disable=no-name-in-module

import os
import tempfile
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

import boto3
from botocore.config import Config
from fastwarc.stream_io import PythonIOStreamAdapter
from fastwarc.warc import ArchiveIterator, WarcRecordType

COMMON_CRAWL_BUCKET = "commoncrawl"
ProgressCallback = Callable[[str], None]


def create_s3_client() -> Any:
    return boto3.client(
        "s3",
        region_name="us-east-1",
        config=Config(
            read_timeout=120,
            connect_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


@contextmanager
def _local_or_downloaded_warc(
    raw_path: str,
    s3_client: Any,
    progress: Optional[ProgressCallback] = None,
) -> Iterator[str]:
    if os.path.exists(raw_path):
        yield raw_path
        return

    with tempfile.NamedTemporaryFile(delete=False, suffix=".warc.gz") as tmp:
        temp_path = tmp.name

    done = threading.Event()

    def heartbeat() -> None:
        while not done.wait(timeout=30):
            if progress:
                progress(raw_path)

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    try:
        s3_client.download_file(
            COMMON_CRAWL_BUCKET,
            raw_path,
            temp_path,
            ExtraArgs={"RequestPayer": "requester"},
        )
        yield temp_path
    finally:
        done.set()
        heartbeat_thread.join(timeout=1)
        if os.path.exists(temp_path):
            os.remove(temp_path)


def iter_response_records(
    raw_path: str,
    s3_client: Any,
    progress: Optional[ProgressCallback] = None,
) -> Iterator[Any]:
    with _local_or_downloaded_warc(raw_path, s3_client, progress) as warc_path:
        with open(warc_path, "rb") as warc_file:
            with PythonIOStreamAdapter(warc_file) as stream:
                yield from ArchiveIterator(
                    stream,
                    record_types=WarcRecordType.response,
                    parse_http=False,
                )
