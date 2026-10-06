"""Causes that are not a recent change: an upstream outage, an expired
certificate, an exhausted resource. Each rule is a pattern over the error
clusters; its score grows with the share of errors it explains."""
from __future__ import annotations

import re

from .correlate import band
from .models import Hypothesis

# (kind, title, pattern, base score, weight of error share, runbook tags)
RULES = [
    ("certificate", "A TLS certificate has expired or is not trusted",
     r"certificate (has )?expired|x509: certificate|CERTIFICATE_VERIFY_FAILED|certificate is not valid", 0.75, 0.2,
     ["certificate", "tls"]),
    ("dependency", "An upstream dependency is failing",
     r"upstream .*(5\d\d|unavailable)|connection refused|connect timeout|503 Service Unavailable|"
     r"upstream connect error|ECONNREFUSED|bad gateway", 0.45, 0.45, ["dependency", "upstream"]),
    ("resource", "The service is running out of memory",
     r"OOMKilled|out of memory|MemoryError|Cannot allocate memory", 0.35, 0.3, ["memory", "oom"]),
    ("resource", "A disk or volume is full",
     r"no space left on device|disk quota exceeded", 0.7, 0.2, ["disk"]),
    ("quota", "A rate limit or quota is being hit",
     r"\b429\b|rate limit|quota exceeded|too many requests", 0.45, 0.4, ["rate-limit", "quota"]),
    ("database", "The database is refusing or blocking queries",
     r"lock wait timeout|deadlock detected|too many connections|could not obtain lock|statement timeout", 0.4, 0.3,
     ["database", "locks"]),
    ("dns", "DNS resolution is failing",
     r"name or service not known|NXDOMAIN|could not resolve host|no such host", 0.6, 0.3, ["dns"]),
]
HOST = re.compile(r"(?:host|upstream|to|connecting to)[ =:\"']+([a-z0-9][a-z0-9.-]*[a-z0-9])", re.IGNORECASE)


def rule_hypotheses(clusters: list) -> list:
    """Return (Hypothesis, matching clusters) pairs."""
    hypotheses = []
    for kind, title, pattern, base, share_weight, tags in RULES:
        regex = re.compile(pattern, re.IGNORECASE)
        matched = [c for c in clusters if regex.search(c.signature) or regex.search(c.example)]
        if not matched:
            continue
        share = min(1.0, sum(c.share for c in matched))
        score = min(0.95, base + share_weight * share)
        target = ""
        if kind == "dependency":
            found = HOST.search(matched[0].example)
            target = found.group(1) if found else ""
        hypothesis = Hypothesis(
            id="", kind=kind, score=round(score, 3), band=band(score),
            title=f"{title}{f' ({target})' if target else ''}",
            factors={"share_of_errors": round(share, 3), "matching_clusters": len(matched)},
            runbook_tags=tags + ([target] if target else []),
        )
        hypotheses.append((hypothesis, matched))
    return hypotheses
