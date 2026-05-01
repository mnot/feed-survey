"""
Generate a mock HTML report with realistic dummy data.

Usage:
    python -m cc_feeds.report.mock [output_path]

Default output_path: mock_report.html
"""

import random
import sys
import zlib
from datetime import datetime, timedelta, timezone
from typing import List

from cc_feeds.analysis import Stats
from cc_feeds.report import generate_report

CRAWL_ID = "CC-MAIN-2026-12"
CRAWL_DATE = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
SEED = 42


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
    h = zlib.crc32(domain.encode("utf-8")) & 0xFFFFFFFF
    idx = h & (stats.hll_m - 1)
    w_bits = 32 - stats.hll_p
    w = h >> stats.hll_p
    rho = (w_bits - w.bit_length() + 1) if w > 0 else (w_bits + 1)
    stats.hll_registers[idx] = max(stats.hll_registers[idx], rho)


def build_mock_stats() -> Stats:
    rng = random.Random(SEED)
    stats = Stats()
    stats.max_crawl_time_str = CRAWL_DATE.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Crawl-level page stats ─────────────────────────────────────────────────
    stats.pages_seen = 4_800_000_000
    stats.pages_processed = 4_800_000_000
    stats.feeds_sniffed = 67_000
    stats.total_entries = 28_000_000

    # ── Content-type distribution ──────────────────────────────────────────────
    stats.content_type_counts = {
        "text/html": 4_650_000_000,
        "application/atom+xml": 680_000,
        "application/rss+xml": 1_250_000,
        "text/xml": 95_000,
        "application/xml": 42_000,
        "application/json": 18_000,
        "text/plain": 8_000,
    }

    # ── HLL for ~32 M unique sites ─────────────────────────────────────────────
    tlds = ["com", "net", "org", "io", "co.uk", "de", "fr", "jp", "au", "ca"]
    for i in range(400_000):
        domain = f"site{i}.{rng.choice(tlds)}"
        _add_hll_site(stats, domain)
    stats.sites_seen_count = stats.get_unique_sites_estimate()

    # ── Discovery relation stats ────────────────────────────────────────────────
    stats.discovery_pages_count = 1_240_000
    stats.discovery_rel_alternate = 1_180_000
    stats.discovery_rel_feed = 90_000
    stats.discovery_rel_both_page = 35_000
    stats.discovery_multi_rel_url = 8_500

    # ── Language stats (global) ────────────────────────────────────────────────
    stats.lang_src_http = 420_000
    stats.lang_src_feed = 980_000
    stats.lang_src_entry = 65_000
    stats.lang_mismatches = 18_000
    stats.lang_multiple_in_feed = 7_200

    # ── Error types ────────────────────────────────────────────────────────────
    stats.error_types = {
        "ParseError": 1_100,
        "XMLSyntaxError": 620,
        "UnicodeDecodeError": 230,
        "ValueError": 100,
    }

    # ── Content length histogram ───────────────────────────────────────────────
    for length_bin, count in [
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
    ]:
        stats.content_length_counts[length_bin] = count

    # ── Feed formats / sample base URLs ────────────────────────────────────────
    formats = [
        ("atom10", 0.38),
        ("rss20", 0.52),
        ("rss10", 0.06),
        ("rss091", 0.02),
        ("rss092", 0.01),
        ("atom03", 0.01),
    ]
    extensions_pool = [
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
    charsets = ["utf-8", "iso-8859-1", "windows-1252", "utf-16", None]
    languages = [
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

    tlds_feed = ["com", "net", "org", "io", "co.uk", "de", "fr", "jp"]
    n_feeds = 50_000

    for i in range(n_feeds):
        # Choose format
        r = rng.random()
        cumulative = 0.0
        fmt = "rss20"
        for name, weight in formats:
            cumulative += weight
            if r < cumulative:
                fmt = name
                break

        domain = f"example{i % 50000}.{rng.choice(tlds_feed)}"
        feed_url = f"https://{domain}/feed{i % 5}.xml"
        page_url = f"https://{domain}/"

        # Dates
        newest = _random_date(rng, 0, 180)
        oldest = _random_date(rng, max(newest[2], 30), 730)  # older than newest
        updated = _random_date(rng, 0, 60) if rng.random() < 0.7 else None
        recently = (
            updated is not None
            and (
                CRAWL_DATE
                - datetime(
                    updated[0],
                    updated[1],
                    updated[2],
                    updated[3],
                    updated[4],
                    updated[5],
                    tzinfo=timezone.utc,
                )
            ).days
            < 7
        )

        # Language
        lang_feed = rng.choice(languages) if rng.random() < 0.85 else None
        lang_http = (
            (lang_feed if rng.random() < 0.9 else rng.choice(languages))
            if lang_feed and rng.random() < 0.4
            else None
        )
        all_langs = set()
        if lang_feed:
            all_langs.add(lang_feed)
        if rng.random() < 0.05:
            all_langs.add(rng.choice(languages))  # occasional multi-lang

        # Extensions
        n_ext = rng.randint(0, 4)
        exts = set(rng.choices(extensions_pool, k=n_ext)) if n_ext else set()

        entry_count = max(0, int(rng.gauss(12, 8)))
        has_content = rng.random() < 0.4
        has_summary = not has_content and rng.random() < 0.8

        feed_info = {
            "url": feed_url,
            "status": 200,
            "content_type": (
                "application/atom+xml" if "atom" in fmt else "application/rss+xml"
            ),
            "charset": rng.choice(charsets),
            "valid": True,
            "format": fmt,
            "entries_count": entry_count,
            "lang_http": lang_http,
            "lang_feed": lang_feed,
            "lang_entries": set(),
            "languages": all_langs | ({lang_feed} if lang_feed else set()),
            "has_summary": has_summary,
            "has_content": has_content,
            "content_type_profile": (
                "html" if has_content or has_summary else "unknown"
            ),
            "all_languages": all_langs,
            "extensions": exts,
            "request_time": CRAWL_DATE,
            "updated_recently": recently,
            "updated_date": updated,
            "newest_entry_date": newest,
            "oldest_entry_date": oldest,
            "title": f"Example Feed {i}",
            "link": page_url,
            "error": None,
        }
        stats.feed_results[feed_url] = feed_info

        # ~60% of feeds have autodiscovery links
        if rng.random() < 0.60:
            n_domains = rng.randint(1, 8)
            domains = [
                f"example{rng.randint(0, 100000)}.{rng.choice(tlds_feed)}"
                for _ in range(n_domains)
            ]
            stats.autodiscovery_links[feed_url] = domains
            stats.discovery_domain_counts[feed_url] = n_domains * rng.randint(1, 20)

    # ── Multi-feed pages ───────────────────────────────────────────────────────
    for i in range(5000):
        page = f"https://example{i}.com/"
        feed_list = [
            f"https://example{i}.com/feed{j}.xml" for j in range(rng.randint(2, 4))
        ]
        stats.multi_feed_pages[page] = feed_list
        for fu in feed_list:
            if fu not in stats.feed_results:
                stats.feed_results[fu] = {
                    "url": fu,
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
                    "title": f"Feed {i}",
                    "link": page,
                    "error": None,
                    "charset": "utf-8",
                    "content_type": "application/atom+xml",
                }
            if fu not in stats.autodiscovery_links:
                stats.autodiscovery_links[fu] = [f"example{i}.com"]
                stats.discovery_domain_counts[fu] = 1

    return stats


def main() -> None:
    output_path = sys.argv[1] if len(sys.argv) > 1 else "mock_report.html"
    print(f"Building mock stats… ", end="", flush=True)
    stats = build_mock_stats()
    n_feeds = len(stats.feed_results)
    n_auto = len(stats.autodiscovery_links)
    print(f"done ({n_feeds:,} feeds, {n_auto:,} with autodiscovery).")
    print(f"Generating report → {output_path}… ", end="", flush=True)
    generate_report(stats, CRAWL_ID, output_path)
    print("done.")


if __name__ == "__main__":
    main()
