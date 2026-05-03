from datetime import datetime, timezone

from cc_feeds.report.quality import is_active_feed, score_components, score_feed

NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _date(day: int) -> list[int]:
    return [2026, 5, day, 0, 0, 0, 4, 0, 0]


def _feed() -> dict[str, object]:
    return {
        "valid": True,
        "error": None,
        "entries_count": 0,
        "has_content": False,
        "has_summary": True,
        "content_lengths": [200],
        "content_type_profile": "plain",
        "lang_entries": set(),
        "title": "Example",
        "link": "https://example.com/",
        "lang_feed": "en",
    }


def test_quality_uses_feed_updated() -> None:
    feed = _feed()
    feed["updated_date"] = _date(1)

    assert score_feed(feed, NOW) > 0.0
    assert score_components(feed, NOW)["recency"] > 0.0
    assert is_active_feed(feed, NOW) is True


def test_quality_rejects_stale_feed() -> None:
    feed = _feed()
    feed["updated_date"] = [2024, 1, 1, 0, 0, 0, 0, 0, 0]

    assert score_feed(feed, NOW) == 0.0
    assert score_components(feed, NOW) == {
        "recency": 0.0,
        "content_richness": 0.0,
        "entry_count": 0.0,
        "entry_metadata": 0.0,
        "feed_metadata": 0.0,
    }
    assert is_active_feed(feed, NOW) is False


def test_quality_stale_entry_wins() -> None:
    feed = _feed()
    feed["newest_entry_date"] = [2024, 1, 1, 0, 0, 0, 0, 0, 0]
    feed["updated_date"] = _date(1)

    assert score_feed(feed, NOW) == 0.0


def test_quality_future_date() -> None:
    feed = _feed()
    feed["updated_date"] = [2099, 1, 1, 0, 0, 0, 0, 0, 0]

    assert score_feed(feed, NOW) == 0.0
    assert is_active_feed(feed, NOW) is False


def test_repeated_titles_penalty() -> None:
    feed = _feed()
    feed["updated_date"] = _date(1)
    feed["newest_entry_date"] = _date(1)
    feed["oldest_entry_date"] = _date(1)
    feed["lang_entries"] = {"en"}
    feed["content_lengths"] = [200, 220]

    clean_score = score_components(feed, NOW)["entry_metadata"]

    feed["repeated_entry_title_ratio"] = 1.0
    feed["default_entry_title_count"] = 2

    assert score_components(feed, NOW)["entry_metadata"] < clean_score


def test_repeated_links_penalty() -> None:
    feed = _feed()
    feed["updated_date"] = _date(1)
    feed["newest_entry_date"] = _date(1)
    feed["oldest_entry_date"] = _date(1)
    feed["lang_entries"] = {"en"}
    feed["content_lengths"] = [200, 220]

    clean_score = score_components(feed, NOW)["entry_metadata"]

    feed["repeated_entry_link_ratio"] = 1.0

    assert score_components(feed, NOW)["entry_metadata"] < clean_score


def test_recent_entries_clear_mid() -> None:
    feed = _feed()
    feed["entries_count"] = 5
    feed["updated_date"] = _date(1)
    feed["newest_entry_date"] = _date(1)
    feed["oldest_entry_date"] = _date(1)
    feed["has_summary"] = False
    feed["content_lengths"] = []
    feed["content_type_profile"] = "unknown"
    feed["lang_entries"] = set()
    feed["repeated_entry_title_ratio"] = 0.0
    feed["repeated_entry_link_ratio"] = 0.0
    feed["default_entry_title_count"] = 0

    assert score_feed(feed, NOW) >= 0.5
