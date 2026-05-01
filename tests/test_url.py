from cc_feeds.url import get_domain, normalize_url


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


def test_get_domain_lowercases_host() -> None:
    assert get_domain("HTTPS://Example.COM:443/path") == "example.com"
