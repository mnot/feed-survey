from typing import Optional, Set

from feed_survey.tranco import get_tranco_list


class SiteScope:
    def __init__(self, top_n: Optional[int] = None) -> None:
        self.top_n_domains: Optional[Set[str]] = (
            get_tranco_list(top_n) if top_n else None
        )
        self._cache: dict[str, bool] = {}

    def includes(self, site: str) -> bool:
        if not self.top_n_domains:
            return True
        if not site:
            return False

        if site in self._cache:
            return self._cache[site]

        in_scope = site in self.top_n_domains

        if len(self._cache) < 50000:
            self._cache[site] = in_scope
        return in_scope


DomainScope = SiteScope
