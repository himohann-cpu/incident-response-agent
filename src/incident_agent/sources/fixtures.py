"""Load an incident from a folder of files, so the agent runs with no live systems."""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Alert, Change


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_services(path: Path) -> dict:
    """Return {service: {"depends_on": [...], "repo": "owner/name"}}."""
    return _json(Path(path))["services"]


class IncidentFixture:
    """alert.json, changes.json and logs.txt, plus optional truth.json and resolution.json."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.id = self.dir.name
        self.alert = Alert.from_dict(_json(self.dir / "alert.json"))
        self._changes = [Change.from_dict(c) for c in _json(self.dir / "changes.json")]
        self.log_text = (self.dir / "logs.txt").read_text(encoding="utf-8")
        self.truth = _json(self.dir / "truth.json") if (self.dir / "truth.json").exists() else None
        self.resolution = _json(self.dir / "resolution.json") if (self.dir / "resolution.json").exists() else None

    def changes(self, since, until) -> list:
        return [c for c in self._changes if since <= c.at <= until]

    def error_lines(self, service, since, until) -> str:
        return self.log_text
