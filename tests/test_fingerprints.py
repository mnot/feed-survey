from cc_feeds.analysis.fingerprints import (
    fingerprint_feed_generator,
    fingerprint_html,
    fingerprint_http_headers,
)


def test_feed_generator_fingerprint() -> None:
    assert fingerprint_feed_generator("WordPress 6.5") == {"wordpress"}


def test_http_header_fingerprint() -> None:
    assert fingerprint_http_headers({"X-Generator": "Drupal 10"}) == {"drupal"}


def test_html_marker_fingerprint() -> None:
    assert fingerprint_html(
        b'<script src="/wp-content/themes/site/app.js"></script>'
    ) == {"wordpress"}


def test_html_generator_attr_order() -> None:
    assert fingerprint_html(
        b'<meta content="Drupal 10" data-x="1" name="generator">'
    ) == {"drupal"}


def test_no_substring_match() -> None:
    assert fingerprint_feed_generator("ImmediateCMS") == set()
