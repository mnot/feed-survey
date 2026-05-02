import argparse
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Optional

import boto3
import requests
from botocore.exceptions import ClientError, NoCredentialsError
from fastwarc.warc import ArchiveIterator  # pylint: disable=no-name-in-module
from tqdm import tqdm

from . import __version__
from .analysis import Stats, WarcProcessor
from .commoncrawl import get_latest_crawl_id, get_warc_paths
from .report import generate_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cc-feeds")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cc-feeds",
        description="Process Common Crawl archives to assess RSS/Atom feed usage.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--topn", type=int, help="Limit to the given top N of the Tranco list"
    )
    parser.add_argument(
        "--crawl-id",
        help="Common Crawl ID (e.g., CC-MAIN-2024-18). Defaults to latest.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run in local mode (downloading archives as necessary)",
    )
    parser.add_argument(
        "--output", default="report.html", help="Path to the output HTML report"
    )
    parser.add_argument(
        "--limit", type=int, help="Number of WARC files to process (default: all)"
    )
    parser.add_argument(
        "--limit-records", type=int, help="Limit number of records per WARC file"
    )
    parser.add_argument("--save-stats", help="Path to save raw stats (pickle)")
    parser.add_argument("--load-stats", help="Path to load raw stats (pickle)")
    parser.add_argument(
        "--use-s3",
        action="store_true",
        help="Stream WARCs from S3 instead of HTTPS (recommended on AWS)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of parallel processes (default: 1)",
    )

    args = parser.parse_args()

    print(f"Starting cc-feeds {__version__}...")

    crawl_id = args.crawl_id or get_latest_crawl_id()
    print(f"Using crawl: {crawl_id}")

    warc_paths = get_warc_paths(crawl_id)
    print(f"Found {len(warc_paths)} WARC files in this crawl.")

    if args.load_stats:
        print(f"Loading stats from {args.load_stats}...")
        stats = Stats.load(args.load_stats)
    else:
        # If limit is specified, slice the paths
        max_warcs = args.limit if args.limit is not None else len(warc_paths)
        active_paths = warc_paths[:max_warcs]

        if args.concurrency > 1:
            print(
                f"Processing {len(active_paths)} WARCs with {args.concurrency} processes..."
            )
            stats = Stats()
            executor = ProcessPoolExecutor(max_workers=args.concurrency)
            try:
                futures = []
                for path in active_paths:
                    futures.append(
                        executor.submit(
                            process_warc,
                            path,
                            args.limit_records,
                            args.topn,
                            args.use_s3,
                        )
                    )

                with tqdm(total=len(futures), desc="WARC Files") as pbar:
                    for future in as_completed(futures):
                        try:
                            warc_stats = future.result()
                            stats.merge(warc_stats)
                        except Exception as exc:  # pylint: disable=broad-except
                            print(f"Error in worker: {exc}")
                        pbar.update(1)
            except KeyboardInterrupt:
                print("\nInterrupt received. Shutting down workers...")
                executor.shutdown(wait=False, cancel_futures=True)
                # Forcefully terminate remaining worker processes
                for process in getattr(executor, "_processes", {}).values():
                    process.terminate()
                raise
            finally:
                executor.shutdown(wait=True)
        else:
            warc_processor = WarcProcessor(top_n=args.topn)
            for idx, warc_path in enumerate(active_paths):
                print(f"[{idx+1}/{max_warcs}] Processing {warc_path}...")
                warc_stats = process_warc(
                    warc_path, args.limit_records, args.topn, args.use_s3
                )
                warc_processor.stats.merge(warc_stats)
            stats = warc_processor.stats

        if args.save_stats:
            print(f"Saving stats to {args.save_stats}...")
            stats.save(args.save_stats)

    print("Processing complete. Generating reports...")
    generate_report(stats, crawl_id, args.output)
    print("Done.")


def process_warc(
    warc_path: str, limit_records: Optional[int], topn: Optional[int], use_s3: bool
) -> Stats:
    """Helper to process a single WARC file, suitable for multiprocessing."""
    processor = WarcProcessor(top_n=topn)

    try:
        body: Any = None
        if use_s3:
            # Common Crawl S3 bucket is Requester Pays
            s3 = boto3.client("s3")
            obj = s3.get_object(
                Bucket="commoncrawl", Key=warc_path, RequestPayer="requester"
            )
            body = obj["Body"]
        else:
            url = f"https://data.commoncrawl.org/{warc_path}"
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            body = response.raw

        warc_iterator = ArchiveIterator(body)
        for record_idx, record in enumerate(warc_iterator):
            if limit_records and record_idx >= limit_records:
                break
            processor.process_record(record)

        return processor.stats
    except NoCredentialsError as exc:
        raise RuntimeError(
            "AWS credentials not found. Run 'aws configure' or use HTTPS."
        ) from exc
    except ClientError as exc:
        if "AccessDenied" in str(exc):
            raise RuntimeError(
                "S3 Access Denied. Ensure your IAM user has S3 access."
            ) from exc
        raise


if __name__ == "__main__":
    main()
