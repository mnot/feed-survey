"""
Feed quality scoring: 0.0 (invalid / dead) to 1.0 (ideal active feed).

Overall score is a weighted sum of five sub-scores, each in [0, 1]:

  recency          0.35  Primary signal. Exponential decay from newest entry
                         date (or feed updated date); half-life = 120 days.
                         A feed updated today scores 1.0; one updated a year
                         ago scores ~0.12.  No date ⟹ 0.

  content_richness 0.25  Does the feed carry useful content?
                         Combination of presence (full content > summary >
                         nothing), average content length (saturates at 1 kB),
                         and content-type profile (html/xhtml > plain).

  entry_count      0.15  Are there enough entries?  Saturates at 20.

  entry_metadata   0.15  Are entries well-tagged?
                         Weighted flags: has entry dates, has oldest date
                         (good coverage), has entry-level language tags, has
                         multiple content-length samples.

  feed_metadata    0.10  Is the feed itself well-described?
                         Weighted flags: title, link, language, updated date.

Invalid or errored feeds always score 0.0.
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "score_feed",
    "WEIGHTS",
    "RECENCY_HALF_LIFE_DAYS",
    "ENTRY_RECENCY_CUTOFF_DAYS",
]

RECENCY_HALF_LIFE_DAYS: float = 120.0
ENTRY_RECENCY_CUTOFF_DAYS: float = 365.0  # no entry in this window → score 0

WEIGHTS: Dict[str, float] = {
    "recency": 0.35,
    "content_richness": 0.25,
    "entry_count": 0.15,
    "entry_metadata": 0.15,
    "feed_metadata": 0.10,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1"


def score_feed(
    feed_info: Dict[str, Any],
    crawl_time: Optional[datetime] = None,
) -> float:
    """
    Return a quality score in [0.0, 1.0] for a single feed result dict.
    Invalid or errored feeds always score 0.0.

    *crawl_time* should be the WARC-Date of the crawl request (or the maximum
    crawl time for the run).  Defaults to UTC now if omitted.
    """
    if not feed_info.get("valid") or feed_info.get("error"):
        return 0.0

    now = crawl_time or datetime.now(timezone.utc)

    # Hard cutoff: no usable recency signal within the last year → dead feed.
    # Prefer entry recency when present; otherwise fall back to feed-level
    # updated date so sparse but active feeds are not forced to zero.
    recency_age = _recency_age_days(feed_info, now)
    if recency_age is None or recency_age > ENTRY_RECENCY_CUTOFF_DAYS:
        return 0.0

    recency = _recency_score(feed_info, now)
    content_richness = _content_richness_score(feed_info)
    entry_count = _entry_count_score(feed_info)
    entry_metadata = _entry_metadata_score(feed_info)
    feed_metadata = _feed_metadata_score(feed_info)

    raw = (
        WEIGHTS["recency"] * recency
        + WEIGHTS["content_richness"] * content_richness
        + WEIGHTS["entry_count"] * entry_count
        + WEIGHTS["entry_metadata"] * entry_metadata
        + WEIGHTS["feed_metadata"] * feed_metadata
    )
    return round(min(max(raw, 0.0), 1.0), 4)


def score_components(
    feed_info: Dict[str, Any],
    crawl_time: Optional[datetime] = None,
) -> Dict[str, float]:
    """
    Return the five sub-scores (each in [0, 1]) without combining them.
    Useful for debugging or detailed reporting.
    """
    if not feed_info.get("valid") or feed_info.get("error"):
        return {k: 0.0 for k in WEIGHTS}

    now = crawl_time or datetime.now(timezone.utc)

    recency_age = _recency_age_days(feed_info, now)
    if recency_age is None or recency_age > ENTRY_RECENCY_CUTOFF_DAYS:
        return {k: 0.0 for k in WEIGHTS}

    return {
        "recency": _recency_score(feed_info, now),
        "content_richness": _content_richness_score(feed_info),
        "entry_count": _entry_count_score(feed_info),
        "entry_metadata": _entry_metadata_score(feed_info),
        "feed_metadata": _feed_metadata_score(feed_info),
    }


# ── Sub-scorers ────────────────────────────────────────────────────────────────


def _date_to_age_days(date_list: Optional[List[int]], now: datetime) -> Optional[float]:
    """Convert a [y,m,d,H,M,S,...] date list to age in days. Returns None on failure."""
    if not date_list:
        return None
    try:
        dt = datetime(
            date_list[0],
            date_list[1],
            date_list[2],
            date_list[3],
            date_list[4],
            date_list[5],
            tzinfo=timezone.utc,
        )
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except (TypeError, ValueError, IndexError):
        return None


def _recency_age_days(feed_info: Dict[str, Any], now: datetime) -> Optional[float]:
    age = _date_to_age_days(feed_info.get("newest_entry_date"), now)
    if age is not None:
        return age
    return _date_to_age_days(feed_info.get("updated_date"), now)


def _recency_score(feed_info: Dict[str, Any], now: datetime) -> float:
    """
    Exponential decay based on the age of the newest entry date.
    Falls back to the feed-level updated date if entry date is absent.
    """
    age = _date_to_age_days(feed_info.get("newest_entry_date"), now)
    if age is None:
        age = _date_to_age_days(feed_info.get("updated_date"), now)
    if age is None:
        return 0.0
    # 2^(-age / half_life): 0 days → 1.0, half_life days → 0.5
    return math.pow(2.0, -age / RECENCY_HALF_LIFE_DAYS)


def _content_richness_score(feed_info: Dict[str, Any]) -> float:
    """
    Combination of:
      - Content presence  (0.50 weight): full content > summary > nothing
      - Average length    (0.30 weight): saturates at 1 kB
      - Content profile   (0.20 weight): html/xhtml > plain > unknown
    """
    has_content = bool(feed_info.get("has_content"))
    has_summary = bool(feed_info.get("has_summary"))
    profile = (feed_info.get("content_type_profile") or "unknown").lower()
    lengths: List[int] = feed_info.get("content_lengths") or []

    presence = 1.0 if has_content else (0.5 if has_summary else 0.0)

    if lengths:
        avg_len = sum(lengths) / len(lengths)
        length_score = min(avg_len / 1000.0, 1.0)
    else:
        length_score = 0.0

    profile_score = {"html": 1.0, "xhtml": 1.0, "mixed": 0.75, "plain": 0.5}.get(
        profile, 0.1
    )

    return 0.50 * presence + 0.30 * length_score + 0.20 * profile_score


def _entry_count_score(feed_info: Dict[str, Any]) -> float:
    """Linear ramp from 0 → 1, saturating at 20 entries."""
    entries_count = feed_info.get("entries_count") or 0
    return min(entries_count / 20.0, 1.0)


def _entry_metadata_score(feed_info: Dict[str, Any]) -> float:
    """
    Weighted boolean flags:
      0.40  has newest entry date   (entries are dated at all)
      0.20  has oldest entry date   (full date coverage across entries)
      0.20  has entry-level language tags
      0.20  has multiple content-length samples (real content in >1 entry)
    """
    score = 0.0
    if feed_info.get("newest_entry_date"):
        score += 0.40
    if feed_info.get("oldest_entry_date"):
        score += 0.20
    if feed_info.get("lang_entries"):
        score += 0.20
    lengths: List[int] = feed_info.get("content_lengths") or []
    if len(lengths) > 1:
        score += 0.20
    return min(score, 1.0)


def _feed_metadata_score(feed_info: Dict[str, Any]) -> float:
    """
    Weighted boolean flags:
      0.30  has title
      0.30  has link
      0.20  has any language signal (feed, HTTP, or xml:lang)
      0.20  has feed-level updated date
    """
    score = 0.0
    if feed_info.get("title"):
        score += 0.30
    if feed_info.get("link"):
        score += 0.30
    if (
        feed_info.get("lang_feed")
        or feed_info.get("lang_http")
        or feed_info.get("all_languages")
    ):
        score += 0.20
    if feed_info.get("updated_date"):
        score += 0.20
    return score
