"""Label-frequency aggregation: 'what problems are common' across an issue set.

Operates on normalized items whose ``labels`` field is a ``list[str]`` (the
client layer flattens GitHub's label objects to names before this point).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from itertools import combinations
from typing import Any


def label_frequency(issues: Iterable[Mapping[str, Any]], *, top_pairs: int = 15) -> dict[str, Any]:
    """Return label counts/shares, top label co-occurrence pairs, and unlabeled count."""
    items = list(issues)
    set_size = len(items)

    counts: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    unlabeled = 0

    for issue in items:
        labels = sorted({str(label) for label in issue.get("labels") or []})
        if not labels:
            unlabeled += 1
            continue
        counts.update(labels)
        pairs.update(combinations(labels, 2))

    labels_out = [
        {"label": label, "count": count, "share": round(count / set_size, 4)}
        for label, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    co_occurrence = [
        {"a": a, "b": b, "count": count}
        for (a, b), count in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))[:top_pairs]
    ]

    return {
        "set_size": set_size,
        "labels": labels_out,
        "co_occurrence": co_occurrence,
        "unlabeled": unlabeled,
    }
