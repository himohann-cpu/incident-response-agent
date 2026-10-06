"""Group error lines by signature so 4,000 lines become a handful of facts."""
from __future__ import annotations

import re
from collections import OrderedDict

from .models import LogCluster, parse_time

ERROR_WORDS = re.compile(r"\b(ERROR|FATAL|CRITICAL|Exception|Traceback|panic|OOMKilled|refused|timed? ?out|"
                         r"expired|denied|5\d\d\b)", re.IGNORECASE)
TIMESTAMP = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s*")
MASKS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b\d+(?:\.\d+)?(ms|s|MB|GB|Mi|Gi|%)\b"), r"<n>\1"),
    (re.compile(r"(?<![\w.])\d+(?![\w.]*\.py)\b"), "<n>"),
]


def signature(line: str) -> str:
    """Mask the parts of a log line that vary between occurrences."""
    text = TIMESTAMP.sub("", line).strip()
    for pattern, replacement in MASKS:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text)[:220]


def cluster_logs(log_text: str, max_clusters: int = 8) -> list:
    """Return the most frequent error signatures, largest first."""
    groups: OrderedDict = OrderedDict()
    for raw in log_text.replace("\r\n", "\n").splitlines():
        if not raw.strip() or not ERROR_WORDS.search(raw):
            continue
        key = signature(raw)
        stamp = TIMESTAMP.match(raw)
        entry = groups.setdefault(key, {"count": 0, "first": None, "example": raw.strip()[:300]})
        entry["count"] += 1
        if stamp and entry["first"] is None:
            try:
                entry["first"] = parse_time(stamp.group(1).replace(" ", "T"))
            except ValueError:
                pass
    total = sum(g["count"] for g in groups.values()) or 1
    ranked = sorted(groups.items(), key=lambda item: -item[1]["count"])[:max_clusters]
    return [LogCluster(signature=key, count=g["count"], share=round(g["count"] / total, 3),
                       first_seen=g["first"], example=g["example"]) for key, g in ranked]
