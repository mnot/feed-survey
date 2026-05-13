from typing import Any


def normalized_content_type(content_type_header: str) -> str:
    return content_type_header.lower().split(";")[0].strip()


def feed_content_type(content_type: str) -> bool:
    return (
        content_type
        in {
            "application/rss+xml",
            "application/atom+xml",
            "application/xml+rss",
            "text/rss",
            "text/atom",
        }
        or content_type.endswith("+rss")
        or content_type.endswith("+atom")
    )


def sniffable_content_type(content_type: str) -> bool:
    return (
        "xml" in content_type
        or "text/plain" in content_type
        or "application/octet-stream" in content_type
    )


def interesting_content_type(content_type_header: str) -> bool:
    content_type = content_type_header.lower()
    return (
        "text/html" in content_type
        or "xml" in content_type
        or "rss" in content_type
        or "text/plain" in content_type
        or "application/octet-stream" in content_type
    )


def interesting_warc_content_type(record: Any) -> bool:
    warc_ct = record.headers.get("WARC-Identified-Payload-Type", "")
    return not warc_ct or interesting_content_type(warc_ct)


def interesting_http_content_type(content_type_header: str) -> bool:
    return interesting_content_type(content_type_header)
