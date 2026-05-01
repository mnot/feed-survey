import re
from typing import Any, Dict, Set
from urllib.parse import urljoin

import lxml.html

from cc_feeds.analysis.stats import Stats
from cc_feeds.url import get_domain, normalize_url

_LINK_RE = re.compile(
    b"<link\\s+[^>]*rel=[\"'](?:alternate|feed)[\"'][^>]*>", re.IGNORECASE
)
_FEED_TYPE_RE = re.compile(
    b"type=[\"']application/(?:rss\\+xml|atom\\+xml|feed\\+json)[\"']",
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
            if not _LINK_RE.search(content) or not _FEED_TYPE_RE.search(content):
                return

            doc = lxml.html.fromstring(content, parser=self.html_parser)
            links = doc.xpath('//link[@rel="alternate" or @rel="feed"]')
            if not isinstance(links, list):
                return

            found_rels: Set[str] = set()
            page_discoveries: Dict[str, Set[str]] = {}
            for link in links:
                if hasattr(link, "get"):
                    self._record_link(page_url, link, found_rels, page_discoveries)

            self._record_page_stats(page_url, found_rels, page_discoveries)
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
            and "feed+json" not in link_type
        ):
            return

        href = link.get("href")
        if not href:
            return

        feed_url = normalize_url(urljoin(page_url, str(href)))
        found_rels.add(rel)
        page_discoveries.setdefault(feed_url, set()).add(rel)

        domain = get_domain(page_url)
        if feed_url not in self.stats.autodiscovery_links:
            self.stats.autodiscovery_links[feed_url] = []
            self.stats.discovery_domain_counts[feed_url] = 0

        self.stats.discovery_domain_counts[feed_url] += 1
        if (
            domain not in self.stats.autodiscovery_links[feed_url]
            and len(self.stats.autodiscovery_links[feed_url]) < 10
        ):
            self.stats.autodiscovery_links[feed_url].append(domain)

    def _record_page_stats(
        self,
        page_url: str,
        found_rels: Set[str],
        page_discoveries: Dict[str, Set[str]],
    ) -> None:
        if found_rels:
            self.stats.discovery_pages_count += 1
        if "alternate" in found_rels:
            self.stats.discovery_rel_alternate += 1
        if "feed" in found_rels:
            self.stats.discovery_rel_feed += 1
        if "alternate" in found_rels and "feed" in found_rels:
            self.stats.discovery_rel_both_page += 1

        if len(page_discoveries) > 1 and len(self.stats.multi_feed_pages) < 10000:
            self.stats.multi_feed_pages[page_url] = list(page_discoveries.keys())
