import math
import pickle
import zlib
from typing import Any, Dict, List, Optional, Set, cast


class _StatsUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if module == "cc_feeds.processor" and name == "Stats":
            return Stats
        return super().find_class(module, name)


class Stats:
    def __init__(self) -> None:
        self.pages_seen: int = 0
        self.sites_seen: Set[str] = set()
        self.sites_seen_count: int = 0
        self.autodiscovery_links: Dict[str, List[str]] = {}
        self.feed_results: Dict[str, Dict[str, Any]] = {}
        self.content_type_counts: Dict[str, int] = {}
        self.error_types: Dict[str, int] = {}
        self.top_n: Optional[int] = None
        self.max_crawl_time_str: Optional[str] = None
        self.feeds_sniffed: int = 0
        self.pages_processed: int = 0
        self.total_entries: int = 0
        self.content_length_counts: Dict[int, int] = {}
        self.discovery_domain_counts: Dict[str, int] = {}

        self.discovery_rel_alternate: int = 0
        self.discovery_rel_feed: int = 0
        self.discovery_rel_both_page: int = 0
        self.discovery_multi_rel_url: int = 0
        self.discovery_pages_count: int = 0
        self.discovery_links_per_page_counts: Dict[int, int] = {}
        self.multi_feed_pages: Dict[str, List[str]] = {}
        self.html_fingerprint_counts: Dict[str, int] = {}
        self.html_fingerprint_auto_counts: Dict[str, int] = {}
        self.feed_source_fingerprints: Dict[str, Dict[str, int]] = {}

        self.hll_p = 12
        self.hll_m = 1 << self.hll_p
        self.hll_registers = [0] * self.hll_m

        self.lang_src_http: int = 0
        self.lang_src_feed: int = 0
        self.lang_src_entry: int = 0
        self.lang_mismatches: int = 0
        self.lang_multiple_in_feed: int = 0

    def merge(self, other: "Stats") -> None:
        """Merge another Stats object into this one."""
        if other.max_crawl_time_str:
            if (
                not self.max_crawl_time_str
                or other.max_crawl_time_str > self.max_crawl_time_str
            ):
                self.max_crawl_time_str = other.max_crawl_time_str
        self.pages_seen += other.pages_seen
        self.feeds_sniffed += other.feeds_sniffed
        self.pages_processed += other.pages_processed
        self.total_entries += other.total_entries

        for length, count in getattr(other, "content_length_counts", {}).items():
            self.content_length_counts[length] = (
                self.content_length_counts.get(length, 0) + count
            )

        self.discovery_rel_alternate += other.discovery_rel_alternate
        self.discovery_rel_feed += other.discovery_rel_feed
        self.discovery_rel_both_page += other.discovery_rel_both_page
        self.discovery_multi_rel_url += other.discovery_multi_rel_url
        self.discovery_pages_count += getattr(other, "discovery_pages_count", 0)
        for count, pages in getattr(
            other, "discovery_links_per_page_counts", {}
        ).items():
            self.discovery_links_per_page_counts[count] = (
                self.discovery_links_per_page_counts.get(count, 0) + pages
            )

        for page_url, feed_urls in getattr(other, "multi_feed_pages", {}).items():
            if page_url not in self.multi_feed_pages:
                self.multi_feed_pages[page_url] = []
            existing = set(self.multi_feed_pages[page_url])
            for feed_url in feed_urls:
                if feed_url not in existing:
                    self.multi_feed_pages[page_url].append(feed_url)

        for label, count in getattr(other, "html_fingerprint_counts", {}).items():
            self.html_fingerprint_counts[label] = (
                self.html_fingerprint_counts.get(label, 0) + count
            )
        for label, count in getattr(other, "html_fingerprint_auto_counts", {}).items():
            self.html_fingerprint_auto_counts[label] = (
                self.html_fingerprint_auto_counts.get(label, 0) + count
            )
        for feed_url, counts in getattr(other, "feed_source_fingerprints", {}).items():
            if feed_url not in self.feed_source_fingerprints:
                self.feed_source_fingerprints[feed_url] = {}
            for label, count in counts.items():
                self.feed_source_fingerprints[feed_url][label] = (
                    self.feed_source_fingerprints[feed_url].get(label, 0) + count
                )

        self.lang_src_http += other.lang_src_http
        self.lang_src_feed += other.lang_src_feed
        self.lang_src_entry += other.lang_src_entry
        self.lang_mismatches += other.lang_mismatches
        self.lang_multiple_in_feed += other.lang_multiple_in_feed
        self.sites_seen.update(other.sites_seen)
        self.sites_seen_count += getattr(other, "sites_seen_count", 0)

        for feed_url, domains in other.autodiscovery_links.items():
            if feed_url not in self.autodiscovery_links:
                self.autodiscovery_links[feed_url] = []
            existing = set(self.autodiscovery_links[feed_url])
            for domain in domains:
                if domain not in existing and len(existing) < 100:
                    self.autodiscovery_links[feed_url].append(domain)
                    existing.add(domain)

        for feed_url, count in getattr(other, "discovery_domain_counts", {}).items():
            self.discovery_domain_counts[feed_url] = (
                self.discovery_domain_counts.get(feed_url, 0) + count
            )

        for content_type, count in other.content_type_counts.items():
            self.content_type_counts[content_type] = (
                self.content_type_counts.get(content_type, 0) + count
            )

        self.feed_results.update(other.feed_results)

        for error_type, count in other.error_types.items():
            self.error_types[error_type] = self.error_types.get(error_type, 0) + count

        other_hll = getattr(other, "hll_registers", None)
        if other_hll:
            for i in range(self.hll_m):
                self.hll_registers[i] = max(self.hll_registers[i], other_hll[i])

        other_top_n = getattr(other, "top_n", None)
        if other_top_n is not None:
            if self.top_n is None or other_top_n > self.top_n:
                self.top_n = other_top_n

    def save(self, path: str) -> None:
        with open(path, "wb") as f_out:
            pickle.dump(self, f_out)

    @classmethod
    def load(cls, path: str) -> "Stats":
        with open(path, "rb") as f_in:
            return cast(Stats, _StatsUnpickler(f_in).load())

    def add_site(self, domain: str) -> None:
        """Add a site to the HLL counter and the set."""
        if not domain:
            return
        self.sites_seen.add(domain)

        hashed_domain = zlib.crc32(domain.encode("utf-8")) & 0xFFFFFFFF

        idx = hashed_domain & (self.hll_m - 1)
        w_bits = 32 - self.hll_p
        remaining_bits = hashed_domain >> self.hll_p
        rho = (
            (w_bits - remaining_bits.bit_length() + 1)
            if remaining_bits > 0
            else (w_bits + 1)
        )
        self.hll_registers[idx] = max(self.hll_registers[idx], rho)

    def get_unique_sites_estimate(self) -> int:
        """Return the HLL estimate of unique sites."""
        alpha = 0.7213 / (1 + 1.079 / self.hll_m)
        z_inverse = sum(2.0**-register for register in self.hll_registers)
        estimate = alpha * (self.hll_m**2) / z_inverse

        if estimate <= 2.5 * self.hll_m:
            zero_registers = self.hll_registers.count(0)
            if zero_registers > 0:
                estimate = self.hll_m * math.log(self.hll_m / zero_registers)
        return int(estimate)
