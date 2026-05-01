#!/usr/bin/env python3
"""Split a WARC paths file into N chunks and upload to an S3 prefix.

Usage: split_paths.py <input> <s3-output-prefix> <n-tasks> [max-paths]
  input: local .txt/.gz file or s3:// path (requester-pays handled automatically)
  max-paths: optional global cap on the number of paths to upload
"""

import gzip
import math
import os
import subprocess
import sys
import tempfile
from typing import List


def read_paths(source: str) -> List[str]:
    if source.startswith("s3://"):
        import boto3

        parts = source[5:].split("/", 1)
        bucket, key = parts[0], parts[1]
        s3 = boto3.client("s3", region_name="us-east-1")
        try:
            resp = s3.get_object(Bucket=bucket, Key=key, RequestPayer="requester")
        except Exception:
            resp = s3.get_object(Bucket=bucket, Key=key)
        data = resp["Body"].read()
        if key.endswith(".gz"):
            data = gzip.decompress(data)
        return [line for line in data.decode("utf-8").splitlines() if line.strip()]
    else:
        opener = gzip.open if source.endswith(".gz") else open
        with opener(source, "rt") as f:
            return [line.rstrip("\n") for line in f if line.strip()]


def main() -> None:
    if len(sys.argv) not in (4, 5):
        print(f"Usage: {sys.argv[0]} <input> <s3-output-prefix> <n-tasks> [max-paths]")
        sys.exit(1)

    source = sys.argv[1]
    dest = sys.argv[2].rstrip("/") + "/"
    n_tasks = int(sys.argv[3])
    max_paths = int(sys.argv[4]) if len(sys.argv) == 5 else 0

    print(f"Reading paths from {source}...")
    lines = read_paths(source)
    if max_paths > 0:
        lines = lines[:max_paths]
        print(f"Limited to first {len(lines)} paths.")
    chunk_size = math.ceil(len(lines) / n_tasks)
    print(f"Splitting {len(lines)} paths into {n_tasks} chunks of ~{chunk_size}...")

    with tempfile.TemporaryDirectory() as tmpdir:
        count = 0
        for i in range(n_tasks):
            chunk = lines[i * chunk_size : (i + 1) * chunk_size]
            if not chunk:
                continue
            with open(os.path.join(tmpdir, f"chunk-{i:05d}.txt"), "w") as f:
                f.write("\n".join(chunk) + "\n")
            count += 1

        print(f"Uploading {count} chunks to {dest}...")
        subprocess.run(["aws", "s3", "sync", tmpdir + "/", dest], check=True)

    print(f"Done: {count} chunks at {dest}")


if __name__ == "__main__":
    main()
