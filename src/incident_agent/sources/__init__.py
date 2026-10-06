"""Where the agent reads from. Every source is read-only.

To plug in your own stack, write a class with the same method as the one you
are replacing:

    class ChangeSource:  def changes(self, since, until) -> list[Change]
    class LogSource:     def error_lines(self, service, since, until) -> str
"""
from .fixtures import IncidentFixture, load_services
from .github import GitHubChangeSource

__all__ = ["IncidentFixture", "GitHubChangeSource", "load_services"]
