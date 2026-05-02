"""
Generate a mock HTML report with realistic dummy data.

Usage:
    python -m cc_feeds.report.mock [output_path]

Default output_path: mock_report.html
"""

import random
import zlib
from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
from typing import Any, List

from cc_feeds.analysis import Stats
from cc_feeds.report import generate_report

CRAWL_ID = "CC-MAIN-2026-12"
CRAWL_DATE = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
SEED = 42
SITE_TLDS = ["com", "net", "org", "io", "co.uk", "de", "fr", "jp", "au", "ca"]
FEED_TLDS = ["com", "net", "org", "io", "co.uk", "de", "fr", "jp"]
FORMAT_WEIGHTS = [
    ("atom10", 0.38),
    ("rss20", 0.52),
    ("rss10", 0.06),
    ("rss091", 0.02),
    ("rss092", 0.01),
    ("atom03", 0.01),
]
EXTENSIONS_POOL = [
    ("http://purl.org/dc/elements/1.1/", "creator"),
    ("http://purl.org/dc/elements/1.1/", "date"),
    ("http://purl.org/dc/elements/1.1/", "subject"),
    ("http://purl.org/dc/terms/", "modified"),
    ("http://purl.org/dc/terms/", "created"),
    ("http://search.yahoo.com/mrss/", "content"),
    ("http://search.yahoo.com/mrss/", "thumbnail"),
    ("http://www.w3.org/2003/01/geo/wgs84_pos#", "lat"),
    ("http://www.w3.org/2003/01/geo/wgs84_pos#", "long"),
    ("http://www.georss.org/georss/", "point"),
    ("http://schemas.google.com/g/2005#", "kind"),
    ("http://wellformedweb.org/CommentAPI/", "commentRssUrl"),
    ("http://purl.org/rss/1.0/modules/slash/", "comments"),
    ("http://webfeeds.org/rss/1.0", "cover"),
    ("http://webfeeds.org/rss/1.0", "accentColor"),
]
CHARSETS = ["utf-8", "iso-8859-1", "windows-1252", "utf-16", None]
LANGUAGES = [
    "en",
    "de",
    "fr",
    "es",
    "ja",
    "zh",
    "pt",
    "ru",
    "it",
    "nl",
    "sv",
    "pl",
    "ar",
    "ko",
    "tr",
    "fi",
    "da",
    "nb",
    "cs",
    "hu",
]
CONTENT_LENGTH_BINS = [
    (0, 800),
    (100, 22_000),
    (200, 48_000),
    (500, 95_000),
    (1000, 140_000),
    (2000, 180_000),
    (5000, 120_000),
    (10000, 60_000),
    (20000, 25_000),
    (50000, 8_000),
    (100000, 1_500),
    (500000, 200),
]


def _date_list(dt: datetime) -> List[int]:
    return [
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.weekday(),
        0,
        0,
    ]


def _random_date(rng: random.Random, min_days_ago: int, max_days_ago: int) -> List[int]:
    days = rng.randint(min_days_ago, max_days_ago)
    dt = CRAWL_DATE - timedelta(days=days, hours=rng.randint(0, 23))
    return _date_list(dt)


def _add_hll_site(stats: Stats, domain: str) -> None:
    hash_value = zlib.crc32(domain.encode("utf-8")) & 0xFFFFFFFF
    idx = hash_value & (stats.hll_m - 1)
    w_bits = 32 - stats.hll_p
    shifted_hash = hash_value >> stats.hll_p
    rho = (w_bits - shifted_hash.bit_length() + 1) if shifted_hash > 0 else (w_bits + 1)
    stats.hll_registers[idx] = max(stats.hll_registers[idx], rho)


def _choose_format(rng: random.Random) -> str:
    format_roll = rng.random()
    cumulative = 0.0
    for name, weight in FORMAT_WEIGHTS:
        cumulative += weight
        if format_roll < cumulative:
            return name
    return "rss20"


def _recently_updated(updated: List[int] | None) -> bool:
    if updated is None:
        return False
    updated_datetime = datetime(
        updated[0],
        updated[1],
        updated[2],
        updated[3],
        updated[4],
        updated[5],
        tzinfo=timezone.utc,
    )
    return (CRAWL_DATE - updated_datetime).days < 7


def _choose_languages(rng: random.Random) -> tuple[str | None, str | None, set[str]]:
    lang_feed = rng.choice(LANGUAGES) if rng.random() < 0.85 else None
    lang_http = (
        (lang_feed if rng.random() < 0.9 else rng.choice(LANGUAGES))
        if lang_feed and rng.random() < 0.4
        else None
    )
    all_langs = set()
    if lang_feed:
        all_langs.add(lang_feed)
    if rng.random() < 0.05:
        all_langs.add(rng.choice(LANGUAGES))
    return lang_feed, lang_http, all_langs


def _populate_crawl_totals(stats: Stats) -> None:
    stats.max_crawl_time_str = CRAWL_DATE.strftime("%Y-%m-%dT%H:%M:%SZ")
    stats.pages_seen = 4_800_000_000
    stats.pages_processed = 4_800_000_000
    stats.feeds_sniffed = 67_000
    stats.total_entries = 28_000_000
    stats.content_type_counts = {
        "text/html": 4_650_000_000,
        "application/atom+xml": 680_000,
        "application/rss+xml": 1_250_000,
        "text/xml": 95_000,
        "application/xml": 42_000,
        "application/json": 18_000,
        "text/plain": 8_000,
    }
    stats.discovery_pages_count = 1_240_000
    stats.discovery_rel_alternate = 1_180_000
    stats.discovery_rel_feed = 90_000
    stats.discovery_rel_both_page = 35_000
    stats.discovery_multi_rel_url = 8_500
    stats.discovery_links_per_page_counts = {
        1: 1_130_000,
        2: 82_000,
        3: 18_000,
        4: 6_500,
        5: 2_000,
        6: 1_000,
        8: 350,
        12: 100,
        20: 40,
        60: 10,
    }
    stats.lang_src_http = 420_000
    stats.lang_src_feed = 980_000
    stats.lang_src_entry = 65_000
    stats.lang_mismatches = 18_000
    stats.lang_multiple_in_feed = 7_200
    stats.error_types = {
        "ParseError": 1_100,
        "XMLSyntaxError": 620,
        "UnicodeDecodeError": 230,
        "ValueError": 100,
    }
    for length_bin, count in CONTENT_LENGTH_BINS:
        stats.content_length_counts[length_bin] = count


def _populate_site_estimate(stats: Stats, rng: random.Random) -> None:
    for idx in range(400_000):
        domain = f"site{idx}.{rng.choice(SITE_TLDS)}"
        _add_hll_site(stats, domain)
    stats.sites_seen_count = stats.get_unique_sites_estimate()


def _build_feed_info(rng: random.Random, idx: int) -> tuple[str, dict[str, Any]]:
    feed_format = _choose_format(rng)
    domain = f"example{idx % 50000}.{rng.choice(FEED_TLDS)}"
    feed_url = f"https://{domain}/feed{idx % 5}.xml"
    page_url = f"https://{domain}/"

    newest = _random_date(rng, 0, 180)
    oldest = _random_date(rng, max(newest[2], 30), 730)
    updated = _random_date(rng, 0, 60) if rng.random() < 0.7 else None
    lang_feed, lang_http, all_langs = _choose_languages(rng)

    n_ext = rng.randint(0, 4)
    extensions = set(rng.choices(EXTENSIONS_POOL, k=n_ext)) if n_ext else set()
    entry_count = max(0, int(rng.gauss(12, 8)))
    has_content = rng.random() < 0.4
    has_summary = not has_content and rng.random() < 0.8

    return feed_url, {
        "url": feed_url,
        "status": 200,
        "content_type": (
            "application/atom+xml" if "atom" in feed_format else "application/rss+xml"
        ),
        "charset": rng.choice(CHARSETS),
        "valid": True,
        "format": feed_format,
        "entries_count": entry_count,
        "lang_http": lang_http,
        "lang_feed": lang_feed,
        "lang_entries": set(),
        "languages": all_langs | ({lang_feed} if lang_feed else set()),
        "has_summary": has_summary,
        "has_content": has_content,
        "content_type_profile": "html" if has_content or has_summary else "unknown",
        "all_languages": all_langs,
        "extensions": extensions,
        "request_time": CRAWL_DATE,
        "updated_recently": _recently_updated(updated),
        "updated_date": updated,
        "newest_entry_date": newest,
        "oldest_entry_date": oldest,
        "title": f"Example Feed {idx}",
        "link": page_url,
        "error": None,
    }


def _populate_feed_results(stats: Stats, rng: random.Random) -> None:
    for idx in range(50_000):
        feed_url, feed_info = _build_feed_info(rng, idx)
        stats.feed_results[feed_url] = feed_info

        if rng.random() < 0.60:
            n_domains = rng.randint(1, 8)
            domains = [
                f"example{rng.randint(0, 100000)}.{rng.choice(FEED_TLDS)}"
                for _ in range(n_domains)
            ]
            stats.autodiscovery_links[feed_url] = domains
            stats.discovery_domain_counts[feed_url] = n_domains * rng.randint(1, 20)


def _add_default_feed(
    stats: Stats, rng: random.Random, feed_url: str, page_url: str, idx: int
) -> None:
    stats.feed_results[feed_url] = {
        "url": feed_url,
        "status": 200,
        "valid": True,
        "format": "atom10",
        "entries_count": 5,
        "lang_http": None,
        "lang_feed": "en",
        "lang_entries": set(),
        "languages": {"en"},
        "has_summary": True,
        "has_content": False,
        "content_type_profile": "html",
        "all_languages": {"en"},
        "extensions": set(),
        "request_time": CRAWL_DATE,
        "updated_recently": False,
        "updated_date": None,
        "newest_entry_date": _random_date(rng, 0, 30),
        "oldest_entry_date": _random_date(rng, 60, 365),
        "title": f"Feed {idx}",
        "link": page_url,
        "error": None,
        "charset": "utf-8",
        "content_type": "application/atom+xml",
    }


def _populate_multi_feed_pages(stats: Stats, rng: random.Random) -> None:
    for idx in range(5000):
        page_url = f"https://example{idx}.com/"
        feed_list = [
            f"https://example{idx}.com/feed{feed_idx}.xml"
            for feed_idx in range(rng.randint(2, 4))
        ]
        stats.multi_feed_pages[page_url] = feed_list
        for feed_url in feed_list:
            if feed_url not in stats.feed_results:
                _add_default_feed(stats, rng, feed_url, page_url, idx)
            if feed_url not in stats.autodiscovery_links:
                stats.autodiscovery_links[feed_url] = [f"example{idx}.com"]
                stats.discovery_domain_counts[feed_url] = 1


def build_mock_stats() -> Stats:
    rng = random.Random(SEED)
    stats = Stats()
    _populate_crawl_totals(stats)
    _populate_site_estimate(stats, rng)
    _populate_feed_results(stats, rng)
    _populate_multi_feed_pages(stats, rng)

    return stats


def main() -> None:
    parser = ArgumentParser(description="Generate a realistic synthetic feed report.")
    parser.add_argument(
        "output_path",
        nargs="?",
        default="mock_report.html",
        help="HTML report output path",
    )
    args = parser.parse_args()

    print("Building mock stats… ", end="", flush=True)
    stats = build_mock_stats()
    n_feeds = len(stats.feed_results)
    n_auto = len(stats.autodiscovery_links)
    print(f"done ({n_feeds:,} feeds, {n_auto:,} with autodiscovery).")
    print(f"Generating report → {args.output_path}… ", end="", flush=True)
    generate_report(stats, CRAWL_ID, args.output_path)
    print("done.")


if __name__ == "__main__":
    main()
