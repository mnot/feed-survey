import cProfile
import io
import os
import pstats
import sys

from fastwarc.stream_io import PythonIOStreamAdapter
from fastwarc.warc import ArchiveIterator, WarcRecordType

# Ensure cc_feeds is in path
sys.path.insert(0, os.getcwd())
from cc_feeds.analysis import WarcProcessor


def run_profile(warc_path):
    processor = WarcProcessor(top_n=500000)

    profiler = cProfile.Profile()
    profiler.enable()

    with open(warc_path, "rb") as f:
        with PythonIOStreamAdapter(f) as stream:
            for record in ArchiveIterator(
                stream, record_types=WarcRecordType.response, parse_http=False
            ):
                processor.process_record(record)

    profiler.disable()
    return profiler, processor


if __name__ == "__main__":
    warc_path = "test/profile_sample.warc.gz"

    profiler, processor = run_profile(warc_path)

    stats = pstats.Stats(profiler).sort_stats("tottime")

    # Print top 30 callers for the most expensive functions
    print("Top 50 functions by tottime:")
    stats.print_stats(50)

    print("\nCallers of decode (iso8859_15):")
    stats.print_callers("iso8859_15")
