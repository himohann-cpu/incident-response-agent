"""Plain data types shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def parse_time(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; a trailing Z or a missing offset means UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def fmt_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@dataclass
class Alert:
    id: str
    service: str
    title: str
    severity: str
    fired_at: datetime
    onset_at: datetime            # when the signal first went bad (often before the alert fired)
    signal: str                   # errors | latency | saturation | availability
    detail: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Alert":
        fired = parse_time(d["fired_at"])
        return cls(id=d["id"], service=d["service"], title=d["title"], severity=d.get("severity", "unknown"),
                   fired_at=fired, onset_at=parse_time(d.get("onset_at", d["fired_at"])),
                   signal=d.get("signal", "errors"), detail=d.get("detail", ""))


@dataclass
class Change:
    """Anything that altered production: a deploy, config change, migration, flag flip."""
    id: str
    service: str
    kind: str                     # deploy | config | migration | dependency | infra | flag | docs
    at: datetime
    summary: str
    author: str = ""
    ref: str = ""                 # commit SHA, change ticket, or URL
    files: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Change":
        return cls(id=d["id"], service=d["service"], kind=d.get("kind", "deploy"), at=parse_time(d["at"]),
                   summary=d.get("summary", ""), author=d.get("author", ""), ref=d.get("ref", ""),
                   files=list(d.get("files", [])))


@dataclass
class LogCluster:
    """Log lines that share a signature once ids and numbers are masked."""
    signature: str
    count: int
    share: float                  # fraction of all error lines
    first_seen: datetime | None
    example: str


@dataclass
class Evidence:
    """One citable fact. The model may only make claims that point at these ids."""
    id: str
    kind: str                     # alert | change | log | topology | rule
    text: str


@dataclass
class Hypothesis:
    id: str
    kind: str                     # change | dependency | certificate | resource | ...
    title: str
    score: float                  # 0..1, computed by code
    band: str                     # high | medium | low
    factors: dict = field(default_factory=dict)     # how the score was built
    evidence: list = field(default_factory=list)    # Evidence ids
    change_id: str | None = None
    runbook_tags: list = field(default_factory=list)
    narrative: str = ""           # explanation; from the model, or a template
    next_check: str = ""
    narrative_source: str = "template"   # template | model


@dataclass
class RunbookMatch:
    id: str
    title: str
    path: str
    score: float
    matched_on: list
    first_steps: list


@dataclass
class ProposedAction:
    """Something a human may choose to do. The agent never executes these."""
    action: str
    command: str
    action_class: str
    needs: str                    # who must approve


@dataclass
class Investigation:
    alert: Alert
    evidence: list
    changes_considered: list
    log_clusters: list
    hypotheses: list
    verdict: str                  # likely_cause | possible_causes | no_clear_cause
    runbooks: list
    actions: list
    status_update: str = ""
    status_update_source: str = "template"
    model: dict = field(default_factory=dict)      # name, tokens, cost, or why it was not used

    def to_dict(self) -> dict:
        def clean(value):
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, list):
                return [clean(v) for v in value]
            return value
        return clean(asdict(self))
