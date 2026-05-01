def guess_feed_format(content: bytes) -> str:
    """Fallback format detection if feedparser fails."""
    try:
        sniff = content[:1000].decode("utf-8", "ignore").lower()
        if "<rss" in sniff:
            return "rss"
        if "<feed" in sniff and 'xmlns="http://www.w3.org/2005/atom"' in sniff:
            return "atom"
        if "<rdf" in sniff:
            return "rdf"
    except (UnicodeDecodeError, AttributeError):
        pass
    return "unknown"
