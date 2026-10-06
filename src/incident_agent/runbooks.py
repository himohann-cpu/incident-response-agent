"""Match runbooks to an incident by tags and services declared in their header.

A runbook is a Markdown file that starts with a small header:

    ---
    id: rollback-deploy
    title: Roll back a deploy
    tags: rollback, deploy
    services: *
    ---
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import RunbookMatch


def load_runbooks(directory: Path) -> list:
    runbooks = []
    for path in sorted(Path(directory).glob("*.md")):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        header = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        if not header:
            continue
        meta = dict(line.split(":", 1) for line in header.group(1).splitlines() if ":" in line)
        meta = {k.strip(): v.strip() for k, v in meta.items()}
        steps = re.findall(r"^\d+\.\s+(.*)$", header.group(2), re.M)
        runbooks.append({
            "id": meta.get("id", path.stem), "title": meta.get("title", path.stem), "path": str(path),
            "tags": {t.strip().lower() for t in meta.get("tags", "").split(",") if t.strip()},
            "services": {s.strip() for s in meta.get("services", "*").split(",")},
            "steps": steps,
        })
    return runbooks


def match_runbooks(runbooks: list, service: str, hypotheses: list, limit: int = 3) -> list:
    """Weight each runbook by the scores of the hypotheses whose tags it shares."""
    matches = []
    for rb in runbooks:
        if "*" not in rb["services"] and service not in rb["services"]:
            continue
        score, matched_on = 0.0, []
        for hyp in hypotheses:
            shared = rb["tags"] & {t.lower() for t in hyp.runbook_tags}
            if shared:
                score += hyp.score * len(shared)
                matched_on.append(f"{hyp.id}: {', '.join(sorted(shared))}")
        if service in rb["services"]:
            score *= 1.2  # a runbook written for this service beats a general one
        if score > 0:
            matches.append(RunbookMatch(id=rb["id"], title=rb["title"], path=rb["path"], score=round(score, 3),
                                        matched_on=matched_on, first_steps=rb["steps"][:3]))
    return sorted(matches, key=lambda m: -m.score)[:limit]
