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
