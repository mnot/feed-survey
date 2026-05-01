from typing import Optional, Set

from cc_feeds.tranco import get_tranco_list


class DomainScope:
    def __init__(self, top_n: Optional[int] = None) -> None:
        self.top_n_domains: Optional[Set[str]] = (
            get_tranco_list(top_n) if top_n else None
        )
        self._cache: dict[str, bool] = {}

    def includes(self, domain: str) -> bool:
        if not self.top_n_domains:
            return True
        if not domain:
            return False

        if domain in self._cache:
            return self._cache[domain]

        in_scope = False
        parts = domain.split(".")
        for idx in range(len(parts)):
            if ".".join(parts[idx:]) in self.top_n_domains:
                in_scope = True
                break

        if len(self._cache) < 50000:
            self._cache[domain] = in_scope
        return in_scope
