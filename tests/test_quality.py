from datetime import datetime, timezone

from cc_feeds.report.quality import score_components, score_feed

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


def test_quality_stale_entry_wins() -> None:
    feed = _feed()
    feed["newest_entry_date"] = [2024, 1, 1, 0, 0, 0, 0, 0, 0]
    feed["updated_date"] = _date(1)

    assert score_feed(feed, NOW) == 0.0
