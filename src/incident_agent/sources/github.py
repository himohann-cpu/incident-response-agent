"""Read recent production changes from GitHub. GET requests only.

Uses the Deployments API when a repo records deployments, and falls back to
commits on the default branch when it does not. Needs a token with read
access in GITHUB_TOKEN; public repos work without one at a low rate limit.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from ..models import Change, parse_time

API = "https://api.github.com"
KIND_BY_PATH = [
    (("migrations/", "alembic/", ".sql"), "migration"),
    (("terraform/", ".tf", "helm/", "k8s/", "Dockerfile", ".github/workflows/"), "infra"),
    (("requirements", "package.json", "package-lock.json", "go.mod", "poetry.lock", "pom.xml"), "dependency"),
    ((".yaml", ".yml", ".toml", ".ini", ".env", "config/"), "config"),
]
DOC_SUFFIXES = (".md", ".rst")


def classify(files: list) -> str:
    """Name the riskiest kind of change present in a list of file paths."""
    for needles, kind in KIND_BY_PATH:
        if any(n in f for f in files for n in needles):
            return kind
    if files and all(f.endswith(DOC_SUFFIXES) for f in files):
        return "docs"
    return "deploy"


class GitHubChangeSource:
    def __init__(self, repos: dict, token: str | None = None, environment: str = "production"):
        """`repos` maps a service name to "owner/name"."""
        self.repos = repos
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.environment = environment

    def _get(self, path: str, **params):
        url = f"{API}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, method="GET", headers={
            "Accept": "application/vnd.github+json", "User-Agent": "incident-agent"})
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _commit_change(self, service: str, repo: str, sha: str, at: datetime | None = None) -> Change:
        commit = self._get(f"/repos/{repo}/commits/{sha}")
        files = [f["filename"] for f in commit.get("files", [])]
        return Change(
            id=f"{service}@{sha[:7]}", service=service, kind=classify(files),
            at=at or parse_time(commit["commit"]["committer"]["date"]),
            summary=commit["commit"]["message"].splitlines()[0][:120],
            author=(commit.get("author") or {}).get("login", ""), ref=commit.get("html_url", sha), files=files)

    def changes(self, since: datetime, until: datetime) -> list:
        found = []
        for service, repo in self.repos.items():
            try:
                deployments = self._get(f"/repos/{repo}/deployments", environment=self.environment, per_page=30)
                in_window = [d for d in deployments if since <= parse_time(d["created_at"]) <= until]
                if in_window:
                    found += [self._commit_change(service, repo, d["sha"], parse_time(d["created_at"]))
                              for d in in_window]
                    continue
                commits = self._get(f"/repos/{repo}/commits", since=since.isoformat(), until=until.isoformat(),
                                    per_page=30)
                found += [self._commit_change(service, repo, c["sha"]) for c in commits]
            except (urllib.error.URLError, KeyError, ValueError) as error:
                # A source that fails must be visible in the report, not silently empty.
                found.append(Change(id=f"{service}@unavailable", service=service, kind="docs", at=since,
                                    summary=f"Could not read changes from GitHub: {error}"))
        return sorted(found, key=lambda c: c.at)
