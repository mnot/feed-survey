from typing import Any, Dict, List, cast


def aggregate_feed_data(results: Dict[str, Any]) -> Dict[str, Any]:
    formats: Dict[str, int] = {}
    languages: Dict[str, int] = {}
    extensions: Dict[Any, int] = {}
    entry_counts: List[int] = []
    last_updated_dates: List[Any] = []
    feeds_with_content = 0
    feeds_with_summary = 0
    feeds_with_neither = 0
    feeds_with_entries = 0
    feeds_with_entry_dates = 0
    feeds_with_updated_date = 0
    feeds_with_repeated_titles = 0
    feeds_with_default_titles = 0
    charsets_per_format: Dict[str, Dict[str, int]] = {}

    total_entries = 0
    lang_src_http = 0
    lang_src_feed = 0
    lang_src_entry = 0
    lang_mismatches = 0
    lang_multiple_in_feed = 0

    for res in results.values():
        res = cast(Dict[str, Any], res)
        if not res.get("valid"):
            continue

        fmt = res.get("format") or "unknown"
        formats[fmt] = formats.get(fmt, 0) + 1

        charset = res.get("charset") or "unknown"
        if fmt not in charsets_per_format:
            charsets_per_format[fmt] = {}
        charsets_per_format[fmt][charset] = charsets_per_format[fmt].get(charset, 0) + 1

        if res.get("languages"):
            for lang in res["languages"]:
                languages[lang] = languages.get(lang, 0) + 1
        else:
            languages["unknown"] = languages.get("unknown", 0) + 1

        if res.get("has_content"):
            feeds_with_content += 1
        elif res.get("has_summary"):
            feeds_with_summary += 1
        else:
            feeds_with_neither += 1

        entries = res.get("entries_count", 0)
        total_entries += entries
        entry_counts.append(entries)
        if entries:
            feeds_with_entries += 1
            if res.get("newest_entry_date"):
                feeds_with_entry_dates += 1

        for ext in res.get("extensions", []):
            ext_key = tuple(ext) if isinstance(ext, (list, tuple)) else ext
            extensions[ext_key] = extensions.get(ext_key, 0) + 1

        if res.get("updated_date"):
            feeds_with_updated_date += 1
            last_updated_dates.append(res["updated_date"])

        if res.get("repeated_entry_title_count"):
            feeds_with_repeated_titles += 1
        if res.get("default_entry_title_count"):
            feeds_with_default_titles += 1

        http_lang = res.get("lang_http")
        feed_lang = res.get("lang_feed")
        entry_langs = res.get("lang_entries", [])

        if http_lang:
            lang_src_http += 1
        if feed_lang:
            lang_src_feed += 1
            if http_lang and http_lang != feed_lang:
                lang_mismatches += 1

        if entry_langs:
            lang_src_entry += 1
            if len(entry_langs) > 1:
                lang_multiple_in_feed += 1

    return {
        "formats": formats,
        "languages": languages,
        "extensions": extensions,
        "entry_counts": entry_counts,
        "last_updated_dates": last_updated_dates,
        "feeds_with_content": feeds_with_content,
        "feeds_with_summary": feeds_with_summary,
        "feeds_with_neither": feeds_with_neither,
        "feeds_with_entries": feeds_with_entries,
        "feeds_with_entry_dates": feeds_with_entry_dates,
        "feeds_with_updated_date": feeds_with_updated_date,
        "feeds_with_repeated_entry_titles": feeds_with_repeated_titles,
        "feeds_with_default_entry_titles": feeds_with_default_titles,
        "charsets_per_format": charsets_per_format,
        "total_entries": total_entries,
        "lang_src_http": lang_src_http,
        "lang_src_feed": lang_src_feed,
        "lang_src_entry": lang_src_entry,
        "lang_mismatches": lang_mismatches,
        "lang_multiple_in_feed": lang_multiple_in_feed,
    }
