from typing import Any, Dict

from cc_feeds.report.formatting import format_extension


def collapse_content_types(content_type_counts: Dict[str, int]) -> Dict[str, int]:
    content_types: Dict[str, int] = {
        "HTML": 0,
        "Atom": 0,
        "RSS": 0,
        "JSON Feed": 0,
        "Other XML": 0,
        "Other": 0,
    }
    for content_type, count in content_type_counts.items():
        content_type_lower = content_type.lower()
        if (
            "text/html" in content_type_lower
            or "application/xhtml" in content_type_lower
        ):
            content_types["HTML"] += count
        elif "atom" in content_type_lower:
            content_types["Atom"] += count
        elif "rss" in content_type_lower:
            content_types["RSS"] += count
        elif "feed+json" in content_type_lower or (
            "json" in content_type_lower and "html" not in content_type_lower
        ):
            content_types["JSON Feed"] += count
        elif "xml" in content_type_lower:
            content_types["Other XML"] += count
        else:
            content_types["Other"] += count
    return content_types


def count_content_profiles(feed_results: Dict[str, Any]) -> Dict[str, int]:
    content_profiles: Dict[str, int] = {
        "html": 0,
        "plain": 0,
        "xhtml": 0,
        "mixed": 0,
        "unknown": 0,
    }
    for result in feed_results.values():
        profile = result.get("content_type_profile", "unknown") or "unknown"
        content_profiles[profile] = content_profiles.get(profile, 0) + 1
    return content_profiles


def count_language_buckets(feed_results: Dict[str, Any]) -> Dict[str, int]:
    language_buckets: Dict[str, int] = {"0": 0, "1": 0, "2": 0, "3+": 0}
    for result in feed_results.values():
        language_count = len(result.get("all_languages") or [])
        if language_count == 0:
            language_buckets["0"] += 1
        elif language_count == 1:
            language_buckets["1"] += 1
        elif language_count == 2:
            language_buckets["2"] += 1
        else:
            language_buckets["3+"] += 1
    return language_buckets


def format_extension_counts(extension_counts: Dict[str, int]) -> Dict[str, int]:
    formatted: Dict[str, int] = {}
    for extension, count in extension_counts.items():
        label = format_extension(extension)
        formatted[label] = formatted.get(label, 0) + count
    return formatted
