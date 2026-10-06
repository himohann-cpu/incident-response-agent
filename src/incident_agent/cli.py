"""Command line entry point.

    incident-agent investigate samples/incidents/01-bad-deploy
    incident-agent postmortem  samples/incidents/01-bad-deploy
    incident-agent eval
    incident-agent github-changes --repo owner/name --hours 48
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .evals import evaluate, render_eval
from .llm import make_client
from .pipeline import investigate
from .render import render_brief, render_postmortem
from .runbooks import load_runbooks
from .sources import GitHubChangeSource, IncidentFixture, load_services

ROOT = Path(__file__).resolve().parents[2]


def _context(args):
    services = load_services(args.services)
    dependencies = {name: spec.get("depends_on", []) for name, spec in services.items()}
    return services, dependencies, load_runbooks(args.runbooks)


def _investigate(args):
    services, dependencies, runbooks = _context(args)
    fx = IncidentFixture(args.incident)
    since = fx.alert.onset_at - timedelta(hours=args.window_hours)
    changes = fx.changes(since, fx.alert.onset_at)
    if args.github:
        repos = {name: spec["repo"] for name, spec in services.items() if spec.get("repo")}
        changes += GitHubChangeSource(repos).changes(since, fx.alert.onset_at)
    inv = investigate(fx.alert, changes, fx.log_text, dependencies, runbooks, llm=make_client(args.provider),
                      window_hours=args.window_hours)
    return fx, inv


def _write(args, name: str, text: str, data: dict | None = None):
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.md").write_text(text, encoding="utf-8")
        if data is not None:
            (out / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Wrote {out / (name + '.md')}")
    else:
        sys.stdout.write(text)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page
    parser = argparse.ArgumentParser(prog="incident-agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--services", default=str(ROOT / "samples" / "services.json"))
    parser.add_argument("--runbooks", default=str(ROOT / "runbooks"))
    parser.add_argument("--provider", choices=["none", "gemini", "claude"], default=None,
                        help="model provider; default is INCIDENT_AGENT_PROVIDER or none")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("investigate", "postmortem"):
        p = sub.add_parser(name)
        p.add_argument("incident", help="folder with alert.json, changes.json, logs.txt")
        p.add_argument("--window-hours", type=int, default=24)
        p.add_argument("--github", action="store_true", help="also read recent changes from GitHub")
        p.add_argument("--out", help="write files here instead of printing")

    p = sub.add_parser("eval")
    p.add_argument("incidents", nargs="?", default=str(ROOT / "samples" / "incidents"))
    p.add_argument("--gate", action="store_true", help="exit 1 if any incident is falsely blamed on a change")

    p = sub.add_parser("github-changes")
    p.add_argument("--repo", required=True, help="owner/name")
    p.add_argument("--hours", type=int, default=48)

    args = parser.parse_args(argv)

    if args.command == "investigate":
        fx, inv = _investigate(args)
        _write(args, f"{fx.id}-brief", render_brief(inv), inv.to_dict())
    elif args.command == "postmortem":
        fx, inv = _investigate(args)
        if not fx.resolution:
            raise SystemExit(f"{fx.dir} has no resolution.json; a postmortem needs the incident to be resolved.")
        _write(args, f"{fx.id}-postmortem", render_postmortem(inv, fx.resolution))
    elif args.command == "eval":
        _, dependencies, runbooks = _context(args)
        make_llm = (lambda: make_client(args.provider)) if make_client(args.provider) else None
        result = evaluate(args.incidents, dependencies, runbooks, make_llm)
        sys.stdout.write(render_eval(result))
        if args.gate and result["metrics"]["false_blame_rate"] > 0:
            print("GATE FAILED: an incident was blamed on a change that did not cause it")
            return 1
    elif args.command == "github-changes":
        now = datetime.now(timezone.utc)
        service = args.repo.split("/")[-1]
        for change in GitHubChangeSource({service: args.repo}).changes(now - timedelta(hours=args.hours), now):
            print(f"{change.at:%Y-%m-%d %H:%M}  {change.kind:<10} {change.id:<28} {change.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
