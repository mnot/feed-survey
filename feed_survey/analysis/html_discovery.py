import re
from typing import Any, Dict, Set
from urllib.parse import urljoin

import lxml.html

from feed_survey.analysis.fingerprints import fingerprint_html
from feed_survey.analysis.stats import Stats
from feed_survey.url import get_site, normalize_url

_LINK_RE = re.compile(
    b"<link\\s+[^>]*rel\\s*=\\s*[\"'][^\"']*(?:alternate|feed)[^\"']*[\"'][^>]*>",
    re.IGNORECASE,
)
_FEED_TYPE_RE = re.compile(
    b"type\\s*=\\s*[\"']application/(?:rss\\+xml|atom\\+xml|rdf\\+xml)"
    b"(?:\\s*;[^\"']*)?[\"']",
    re.IGNORECASE,
)


class HtmlDiscovery:
    def __init__(self, stats: Stats) -> None:
        self.stats = stats
        self.html_parser = lxml.html.HTMLParser(recover=True, encoding="utf-8")

    def process(self, page_url: str, content: bytes) -> None:
        if not content:
            return

        try:
            fingerprints = fingerprint_html(content)
            if fingerprints:
                self.stats.html_fp_pages += 1
            for fingerprint in fingerprints:
                self.stats.html_fingerprint_counts[fingerprint] = (
                    self.stats.html_fingerprint_counts.get(fingerprint, 0) + 1
                )

            if not _LINK_RE.search(content) or not _FEED_TYPE_RE.search(content):
                return

            doc = lxml.html.fromstring(content, parser=self.html_parser)
            links = doc.xpath("//link[@rel]")
            if not isinstance(links, list):
                return

            found_rels: Set[str] = set()
            page_discoveries: Dict[str, Set[str]] = {}
            for link in links:
                if hasattr(link, "get"):
                    self._record_link(page_url, link, found_rels, page_discoveries)

            has_discovery = self._record_page_stats(
                page_url, found_rels, page_discoveries
            )
            if has_discovery:
                if fingerprints:
                    self.stats.html_fp_auto_pages += 1
                for fingerprint in fingerprints:
                    self.stats.html_fingerprint_auto_counts[fingerprint] = (
                        self.stats.html_fingerprint_auto_counts.get(fingerprint, 0) + 1
                    )
                self._record_source_fingerprints(page_discoveries, fingerprints)
        except (LookupError, RuntimeError, SyntaxError, TypeError, ValueError):
            pass

    def _record_link(
        self,
        page_url: str,
        link: Any,
        found_rels: Set[str],
        page_discoveries: Dict[str, Set[str]],
    ) -> None:
        rel = str(link.get("rel", "")).lower()
        link_type = str(link.get("type", "")).lower()
        if (
            "rss+xml" not in link_type
            and "atom+xml" not in link_type
            and "rdf+xml" not in link_type
        ):
            return

        rel_tokens = set(rel.split())
        feed_rel_tokens = rel_tokens & {"alternate", "feed"}
        if not feed_rel_tokens:
            return

        href = link.get("href")
        if not href:
            return

        feed_url = normalize_url(urljoin(page_url, str(href)))
        found_rels.update(feed_rel_tokens)
        page_discoveries.setdefault(feed_url, set()).update(feed_rel_tokens)

        site = get_site(page_url)
        if feed_url not in self.stats.autodiscovery_links:
            self.stats.autodiscovery_links[feed_url] = []
            self.stats.discovery_domain_counts[feed_url] = 0

        self.stats.discovery_domain_counts[feed_url] += 1
        if (
            site not in self.stats.autodiscovery_links[feed_url]
            and len(self.stats.autodiscovery_links[feed_url]) < 10
        ):
            self.stats.autodiscovery_links[feed_url].append(site)

    def _record_page_stats(
        self,
        page_url: str,
        found_rels: Set[str],
        page_discoveries: Dict[str, Set[str]],
    ) -> bool:
        if found_rels:
            self.stats.discovery_pages_count += 1
        if "alternate" in found_rels:
            self.stats.discovery_rel_alternate += 1
        if "feed" in found_rels:
            self.stats.discovery_rel_feed += 1
        if "alternate" in found_rels and "feed" in found_rels:
            self.stats.discovery_rel_both_page += 1
        both_rel_links = sum(
            1 for rel_tokens in page_discoveries.values() if len(rel_tokens) > 1
        )
        if both_rel_links:
            self.stats.discovery_link_rel_both_page += 1
        self.stats.discovery_link_rel_both += both_rel_links
        self.stats.discovery_multi_rel_url += both_rel_links
        feed_count = len(page_discoveries)
        if feed_count:
            self.stats.discovery_links_per_page_counts[feed_count] = (
                self.stats.discovery_links_per_page_counts.get(feed_count, 0) + 1
            )

        if len(page_discoveries) > 1 and len(self.stats.multi_feed_pages) < 10000:
            self.stats.multi_feed_pages[page_url] = list(page_discoveries.keys())
        return bool(found_rels)

    def _record_source_fingerprints(
        self, page_discoveries: Dict[str, Set[str]], fingerprints: Set[str]
    ) -> None:
        source_fingerprints = fingerprints or {"unknown"}
        for feed_url in page_discoveries:
            if feed_url not in self.stats.feed_source_fingerprints:
                self.stats.feed_source_fingerprints[feed_url] = {}
            for fingerprint in source_fingerprints:
                self.stats.feed_source_fingerprints[feed_url][fingerprint] = (
                    self.stats.feed_source_fingerprints[feed_url].get(fingerprint, 0)
                    + 1
                )
