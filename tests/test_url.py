from feed_survey.url import (
    get_domain,
    get_host,
    get_site,
    normalize_url,
    normalize_url_for_grouping,
)


def test_normalize_keeps_path_case() -> None:
    assert (
        normalize_url("HTTPS://Example.COM/Feeds/Main.XML")
        == "https://example.com/Feeds/Main.XML"
    )


def test_normalize_strips_fragment() -> None:
    assert (
        normalize_url("https://Example.COM/Feeds/Main.XML?x=1#entry")
        == "https://example.com/Feeds/Main.XML?x=1"
    )


def test_normalize_default_port() -> None:
    assert normalize_url("https://Example.COM:443/feed.xml") == (
        "https://example.com/feed.xml"
    )
    assert normalize_url("http://Example.COM:80/feed.xml") == (
        "http://example.com/feed.xml"
    )


def test_normalize_custom_port() -> None:
    assert (
        normalize_url("https://Example.COM:8443/feed.xml")
        == "https://example.com:8443/feed.xml"
    )


def test_grouping_url_strips_query() -> None:
    assert (
        normalize_url_for_grouping("https://Example.COM/Feeds/Main.XML?x=1#entry")
        == "https://example.com/Feeds/Main.XML"
    )


def test_get_domain_lowercases_host() -> None:
    assert get_domain("HTTPS://Example.COM:443/path") == "example.com"
    assert get_host("HTTPS://Example.COM:443/path") == "example.com"


def test_get_domain_userinfo() -> None:
    assert get_domain("http://user:pass@Example.COM/feed") == "example.com"


def test_get_domain_handles_ipv6() -> None:
    assert get_domain("http://[2001:db8::1]:8080/feed") == "2001:db8::1"


def test_get_site_uses_psl() -> None:
    assert get_site("https://www.Example.CO.UK/feed") == "example.co.uk"


def test_get_site_keeps_private_psl() -> None:
    assert get_site("https://foo.github.io/feed") == "foo.github.io"
    assert get_site("https://www.foo.blogspot.com/feed") == "foo.blogspot.com"


def test_get_site_keeps_ip_literals() -> None:
    assert get_site("http://127.0.0.1/feed") == "127.0.0.1"
    assert get_site("http://[2001:db8::1]:8080/feed") == "2001:db8::1"


def test_get_site_matches_www() -> None:
    assert get_site("www.Example.COM") == "example.com"
    assert get_site("https://www.Example.COM/feed") == "example.com"
