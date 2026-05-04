from feed_survey.analysis.processor import _interesting_content_type


def test_json_not_interesting() -> None:
    assert _interesting_content_type("application/feed+json") is False
    assert _interesting_content_type("application/json") is False


def test_xml_html_interesting() -> None:
    assert _interesting_content_type("application/rss+xml") is True
    assert _interesting_content_type("application/atom+xml") is True
    assert _interesting_content_type("text/html; charset=utf-8") is True


def test_sniffable_ct_interesting() -> None:
    assert _interesting_content_type("text/plain") is True
    assert _interesting_content_type("application/octet-stream") is True
