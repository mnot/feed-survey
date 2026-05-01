from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

_CDF_BREAKPOINTS: List[Tuple[int, str]] = [
    (0, "Today"),
    (1, "1 day"),
    (3, "3 days"),
    (7, "1 week"),
    (14, "2 weeks"),
    (30, "1 month"),
    (90, "3 months"),
    (180, "6 months"),
    (365, "1 year"),
    (730, "2 years"),
    (10000, "All"),
]


def make_histogram(
    data: Union[Sequence[Any], Dict[Any, int]],
    bins: Optional[str] = None,
    log_scale: bool = False,
) -> Dict[str, int]:
    if not data:
        return {}

    if isinstance(data, dict):
        counts = data
    else:
        counts = {}
        for item in data:
            counts[item] = counts.get(item, 0) + 1

    if not counts:
        return {}

    if bins == "natural":
        hist = _natural_histogram(counts)
    elif log_scale:
        hist = _log_histogram(counts)
    elif bins == "discovery":
        hist = _discovery_histogram(counts)
    elif bins == "entries":
        hist = _entry_histogram(counts)
    else:
        hist = _simple_histogram(counts)
    return hist


def build_recency_cdf(
    results: Dict[str, Any], key: str, now: datetime
) -> Dict[str, Any]:
    """
    Build a CDF for recency data.

    For each breakpoint in _CDF_BREAKPOINTS, computes the percentage of feeds
    whose *key* date is at most that many days before *now*.
    """
    ages: List[int] = []
    total = len(results)
    for info in results.values():
        val = info.get(key)
        if not val:
            continue
        try:
            dt = datetime(
                val[0], val[1], val[2], val[3], val[4], val[5], tzinfo=timezone.utc
            )
            ages.append(max(0, (now - dt).days))
        except (ValueError, TypeError, IndexError):
            pass

    ages.sort()
    dated_count = len(ages)
    labels: List[str] = []
    data: List[float] = []
    for days, label in _CDF_BREAKPOINTS:
        lo, hi = 0, dated_count
        while lo < hi:
            mid = (lo + hi) // 2
            if ages[mid] <= days:
                lo = mid + 1
            else:
                hi = mid
        pct = round(lo / dated_count * 100, 1) if dated_count else 0.0
        labels.append(label)
        data.append(pct)
    return {"labels": labels, "data": data, "no_date": total - dated_count}


def _natural_histogram(counts: Dict[Any, int]) -> Dict[str, int]:
    labels = ["0", "-127", "-254", "-511", "-1023"]
    thresholds = [0, 127, 254, 511, 1023]

    max_val = max(counts.keys()) if counts else 0
    curr = 1024
    while curr <= max_val:
        labels.append(f"-{curr*2//1024}k")
        thresholds.append(curr * 2 - 1)
        curr *= 2

    hist = {label: 0 for label in labels}
    for val, count in counts.items():
        if val == 0:
            hist["0"] += count
            continue
        for idx, threshold in enumerate(thresholds):
            if idx == 0:
                continue
            if val <= threshold:
                hist[labels[idx]] += count
                break
    return hist


def _log_histogram(counts: Dict[Any, int]) -> Dict[str, int]:
    labels = [
        "0-100",
        "100-500",
        "500-1k",
        "1k-5k",
        "5k-10k",
        "10k-50k",
        "50k-100k",
        "100k-500k",
        "500k+",
    ]
    thresholds: List[Union[int, float]] = [
        100,
        500,
        1000,
        5000,
        10000,
        50000,
        100000,
        500000,
        float("inf"),
    ]
    hist = {label: 0 for label in labels}
    for val, count in counts.items():
        for idx, threshold in enumerate(thresholds):
            if val < threshold:
                hist[labels[idx]] += count
                break
    return hist


def _discovery_histogram(counts: Dict[Any, int]) -> Dict[str, int]:
    labels = (
        ["0"]
        + [str(i) for i in range(1, 11)]
        + [
            "-15",
            "-20",
            "-50",
            "-100",
            "100+",
        ]
    )
    hist = {label: 0 for label in labels}
    for val, count in counts.items():
        if val == 0:
            hist["0"] += count
        elif val <= 10:
            hist[str(val)] += count
        elif val <= 15:
            hist["-15"] += count
        elif val <= 20:
            hist["-20"] += count
        elif val <= 50:
            hist["-50"] += count
        elif val <= 100:
            hist["-100"] += count
        else:
            hist["100+"] += count
    return hist


def _entry_histogram(counts: Dict[Any, int]) -> Dict[str, int]:
    labels = [
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11-15",
        "16-20",
        "21-30",
        "31-50",
        "51-100",
        "100+",
    ]
    hist = {label: 0 for label in labels}
    for val, count in counts.items():
        if val <= 10:
            hist[str(val)] += count
        elif val <= 15:
            hist["11-15"] += count
        elif val <= 20:
            hist["16-20"] += count
        elif val <= 30:
            hist["21-30"] += count
        elif val <= 50:
            hist["31-50"] += count
        elif val <= 100:
            hist["51-100"] += count
        else:
            hist["100+"] += count
    return hist


def _simple_histogram(counts: Dict[Any, int]) -> Dict[str, int]:
    max_val = max(counts.keys())
    if max_val == 0:
        return {"0": sum(counts.values())}
    bin_size = max(1, max_val // 10)
    hist: Dict[str, int] = {}
    for val, count in counts.items():
        bin_idx = val // bin_size
        low = bin_idx * bin_size
        high = (bin_idx + 1) * bin_size - 1
        label = (
            str(low)
            if low == high
            else f"-{high//1024}k" if high >= 1024 else f"-{high}"
        )
        hist[label] = hist.get(label, 0) + count
    return dict(
        sorted(
            hist.items(),
            key=lambda item: (
                int(item[0].lstrip("-").rstrip("k+")) * 1024
                if "k" in item[0]
                else int(item[0].lstrip("-").rstrip("+"))
            ),
        )
    )
