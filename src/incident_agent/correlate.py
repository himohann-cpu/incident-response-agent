"""Score every recent change for how likely it is to have caused the alert.

The score is a weighted sum of four factors, each between 0 and 1, and each
kept in the output so a responder can see why a change ranked where it did.
"""
from __future__ import annotations

import math
import re
from pathlib import PurePosixPath

from .models import Alert, Change, Hypothesis

WEIGHTS = {"timing": 0.35, "topology": 0.25, "log_overlap": 0.30, "change_risk": 0.10}
CHANGE_RISK = {"migration": 0.9, "config": 0.8, "infra": 0.8, "flag": 0.7, "dependency": 0.7,
               "deploy": 0.6, "docs": 0.0}
# How quickly suspicion fades with time between the change and the onset.
# Saturation problems (memory, disk) build slowly, so a change hours earlier still counts.
DECAY_MINUTES = {"saturation": 360.0}
DEFAULT_DECAY_MINUTES = 45.0
UNRELATED_CAP = 0.2            # a change to an unrelated service can never rank above this
HIGH, MEDIUM = 0.6, 0.4
RUNBOOK_TAGS = {"deploy": ["rollback", "deploy"], "config": ["config"], "flag": ["config", "flag"],
                "migration": ["migration"], "dependency": ["dependency-bump", "rollback"], "infra": ["infra"]}
GENERIC_STEMS = {"main", "index", "app", "init", "__init__", "config", "settings", "utils", "test"}


def band(score: float) -> str:
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"


def timing_factor(change: Change, alert: Alert) -> float:
    minutes = (alert.onset_at - change.at).total_seconds() / 60
    if minutes < 0:
        return 0.0  # the change happened after things went wrong
    return math.exp(-minutes / DECAY_MINUTES.get(alert.signal, DEFAULT_DECAY_MINUTES))


def topology_factor(change: Change, alert: Alert, dependencies: dict) -> float:
    if change.service == alert.service:
        return 1.0
    direct = dependencies.get(alert.service, [])
    if change.service in direct:
        return 0.7
    if any(change.service in dependencies.get(d, []) for d in direct):
        return 0.3
    return 0.0


def log_overlap_factor(change: Change, clusters: list) -> tuple:
    """1.0 if a changed file path appears in the errors, 0.5 for a distinctive file name."""
    text = "\n".join(f"{c.signature}\n{c.example}" for c in clusters)
    best, hits = 0.0, []
    for path in change.files:
        pure = PurePosixPath(path.replace("\\", "/"))
        if str(pure) in text:
            best, hits = 1.0, hits + [str(pure)]
        elif pure.stem.lower() not in GENERIC_STEMS and len(pure.stem) > 3 and \
                re.search(rf"\b{re.escape(pure.name)}\b", text):
            best, hits = max(best, 0.5), hits + [pure.name]
    return best, hits


def score_changes(alert: Alert, changes: list, clusters: list, dependencies: dict) -> list:
    """Return one Hypothesis per change that happened before the onset, best first."""
    hypotheses = []
    for change in changes:
        timing = timing_factor(change, alert)
        if timing == 0.0 or change.kind == "docs":
            continue  # after the onset, or not a change to running software
        topology = topology_factor(change, alert, dependencies)
        overlap, hits = log_overlap_factor(change, clusters)
        factors = {
            "timing": round(timing, 3),
            "topology": topology,
            "log_overlap": overlap,
            "change_risk": CHANGE_RISK.get(change.kind, 0.5),
        }
        score = sum(WEIGHTS[name] * value for name, value in factors.items())
        if topology == 0.0:
            score = min(score, UNRELATED_CAP)
        minutes = round((alert.onset_at - change.at).total_seconds() / 60)
        factors["minutes_before_onset"] = minutes
        if hits:
            factors["files_seen_in_errors"] = sorted(set(hits))
        hypotheses.append(Hypothesis(
            id="", kind="change", change_id=change.id, score=round(score, 3), band=band(score),
            title=f"{change.kind.capitalize()} to {change.service} {minutes} min before onset: {change.summary}",
            factors=factors, runbook_tags=RUNBOOK_TAGS.get(change.kind, [change.kind]),
        ))
    return sorted(hypotheses, key=lambda h: -h.score)
