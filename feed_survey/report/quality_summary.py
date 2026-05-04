from datetime import datetime
from typing import Any, Dict, List, cast

from feed_survey.report.quality import (
    ENTRY_RECENCY_CUTOFF_DAYS,
    QUALITY_SPLIT_THRESHOLD,
    WEIGHTS,
    is_active_feed,
    recency_age_days,
    score_components,
    score_feed,
)


def build_quality_summary(
    all_valid_results: Dict[str, Any],
    discovered_results: Dict[str, Any],
    discovered_urls: set[str],
    now: datetime,
) -> Dict[str, Any]:
    quality_hist: Dict[str, int] = {
        f"{idx/10:.1f}–{(idx+1)/10:.1f}": 0 for idx in range(10)
    }
    quality_scores: List[float] = []
    active_scores: List[float] = []
    active_with_entries_count = 0
    mid_quality_count = 0
    undated_count = 0
    stale_count = 0
    format_scores: Dict[str, List[float]] = {}
    component_scores: Dict[str, List[float]] = {key: [] for key in WEIGHTS}

    for result in all_valid_results.values():
        score = score_feed(result, now)
        quality_scores.append(score)
        if score > QUALITY_SPLIT_THRESHOLD:
            mid_quality_count += 1
        if is_active_feed(result, now):
            active_scores.append(score)
            if (result.get("entries_count") or 0) > 0:
                active_with_entries_count += 1
        else:
            age = recency_age_days(result, now)
            if age is None:
                undated_count += 1
            elif age > ENTRY_RECENCY_CUTOFF_DAYS:
                stale_count += 1
        components = score_components(result, now)
        for key, component_score in components.items():
            component_scores[key].append(component_score)
        bin_idx = min(int(score * 10), 9)
        label = f"{bin_idx/10:.1f}–{(bin_idx+1)/10:.1f}"
        quality_hist[label] += 1

        feed_format = result.get("format") or "unknown"
        format_scores.setdefault(feed_format, []).append(score)

    no_autodiscovery_results = {
        url: result
        for url, result in all_valid_results.items()
        if url not in discovered_urls
    }

    return {
        "hist": quality_hist,
        "mean": _mean(quality_scores),
        "active": {
            "mean": round(_mean(active_scores), 3),
            "n": len(active_scores),
            "with_entries": active_with_entries_count,
            "without_entries": len(active_scores) - active_with_entries_count,
            "pct": (
                round(len(active_scores) / len(quality_scores) * 100, 1)
                if quality_scores
                else 0.0
            ),
        },
        "inactive": {
            "n": undated_count + stale_count,
            "undated": undated_count,
            "stale": stale_count,
            "cutoff_days": int(ENTRY_RECENCY_CUTOFF_DAYS),
        },
        "components": _component_rows(component_scores),
        "format_rows": _format_quality_rows(format_scores),
        "autodiscovery": _quality_dist(discovered_results, now),
        "no_autodiscovery": _quality_dist(no_autodiscovery_results, now),
    }


def _component_rows(component_scores: Dict[str, List[float]]) -> List[Dict[str, Any]]:
    labels = {
        "recency": "Recency",
        "content_richness": "Content",
        "entry_count": "Entry count",
        "entry_metadata": "Entry metadata",
        "feed_metadata": "Feed metadata",
    }
    return [
        {
            "key": key,
            "label": labels[key],
            "weight": WEIGHTS[key],
            "mean": round(_mean(scores), 3),
        }
        for key, scores in component_scores.items()
    ]


def _format_quality_rows(format_scores: Dict[str, List[float]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for feed_format, scores in format_scores.items():
        count = len(scores)
        format_mid_quality_count = sum(
            1 for score in scores if score > QUALITY_SPLIT_THRESHOLD
        )
        rows.append(
            {
                "fmt": feed_format,
                "count": count,
                "quality_count": format_mid_quality_count,
                "quality_pct": round(format_mid_quality_count / count * 100, 1),
                "mean": round(_mean(scores), 3),
                "high_pct": round(
                    sum(1 for score in scores if score >= 0.7) / count * 100, 1
                ),
                "mid_pct": round(
                    sum(1 for score in scores if 0.4 <= score < 0.7) / count * 100,
                    1,
                ),
                "low_pct": round(
                    sum(1 for score in scores if score < 0.4) / count * 100, 1
                ),
            }
        )
    rows.sort(key=lambda row: cast(float, row["mean"]), reverse=True)
    return rows


def _quality_dist(results: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    scores = [score_feed(result, now) for result in results.values()]
    count = len(scores)
    bins = [f"{idx/10:.1f}–{(idx+1)/10:.1f}" for idx in range(10)]
    hist = {bin_label: 0 for bin_label in bins}
    for score in scores:
        bin_idx = min(int(score * 10), 9)
        hist[f"{bin_idx/10:.1f}–{(bin_idx+1)/10:.1f}"] += 1
    pct = {
        bin_label: round(hist[bin_label] / count * 100, 1) if count else 0.0
        for bin_label in bins
    }
    return {
        "labels": bins,
        "pct": list(pct.values()),
        "mean": round(_mean(scores), 3),
        "n": count,
    }


def _mean(scores: List[float]) -> float:
    return sum(scores) / len(scores) if scores else 0.0
