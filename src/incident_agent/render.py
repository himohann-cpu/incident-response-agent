"""Markdown for humans: the incident brief and the postmortem draft.

Facts are written by this module straight from the data. Model-written text
is confined to labelled fields.
"""
from __future__ import annotations

from .models import fmt_time, parse_time

VERDICT_TEXT = {
    "likely_cause": "One cause stands clearly ahead of the others.",
    "possible_causes": "More than one cause fits the evidence. Do not treat the first as confirmed.",
    "no_clear_cause": "Nothing in the evidence singles out a cause. Start with the triage runbook.",
}


def _minutes(start, end) -> str:
    minutes = round((end - start).total_seconds() / 60)
    return f"{minutes} min" if minutes < 120 else f"{minutes / 60:.1f} h"


def render_brief(inv) -> str:
    a = inv.alert
    out = [
        f"# Incident brief: {a.title}",
        "",
        f"**Service:** {a.service} · **Severity:** {a.severity} · **Signal went bad:** {fmt_time(a.onset_at)} · "
        f"**Alert fired:** {fmt_time(a.fired_at)}",
        "",
        f"**Verdict:** `{inv.verdict}`. {VERDICT_TEXT[inv.verdict]}",
        "",
        "## Ranked hypotheses",
        "",
        "Scores and ranking are computed by code. Explanations marked *model* were written by the model "
        "and checked against the evidence ids they cite.",
        "",
    ]
    if not inv.hypotheses:
        out += ["No candidate causes were found in the evidence.", ""]
    for h in inv.hypotheses:
        factors = ", ".join(f"{k} {v}" for k, v in h.factors.items() if not isinstance(v, list))
        out += [
            f"### {h.id}. {h.title}",
            "",
            f"**Score:** {h.score:.2f} ({h.band}) · **Evidence:** {', '.join(h.evidence)} · **Factors:** {factors}",
            "",
            f"{h.narrative} *({h.narrative_source})*",
            "",
        ]
        if h.next_check:
            out += [f"**Check next:** {h.next_check}", ""]

    out += ["## Suggested runbooks", ""]
    if inv.runbooks:
        for rb in inv.runbooks:
            out.append(f"- **{rb.title}** (`{rb.id}`), matched on {'; '.join(rb.matched_on) or 'triage'}")
            out += [f"  {i}. {step}" for i, step in enumerate(rb.first_steps, start=1)]
    else:
        out.append("No runbook matched.")

    out += ["", "## Proposed actions", "", "The agent does not execute anything. Each action needs the approval shown.", ""]
    if inv.actions:
        out += ["| Action | Command | Needs approval from |", "|---|---|---|"]
        out += [f"| {x.action} | {f'`{x.command}`' if x.command else 'see runbook'} | {x.needs} |" for x in inv.actions]
    else:
        out.append("None proposed.")

    out += ["", "## Draft status update", "", f"> {inv.status_update} *({inv.status_update_source})*", "",
            "## Evidence", "", "| Id | Kind | Fact |", "|---|---|---|"]
    out += [f"| {e.id} | {e.kind} | {e.text.replace('|', chr(92) + '|')[:400]} |" for e in inv.evidence]

    m = inv.model
    out += ["", "## Model usage", ""]
    if m.get("used"):
        cost = f"${m['cost_usd']:.4f}" if m.get("cost_usd") is not None else "not priced"
        out.append(f"Model `{m['model']}`: {m['input_tokens']} input and {m['output_tokens']} output tokens, cost {cost}.")
        if m.get("rejected"):
            out += ["", "Rejected from the model's reply:"] + [f"- {r}" for r in m["rejected"]]
    else:
        out.append(f"No model output was used ({m.get('reason')}). Everything above comes from code.")
    return "\n".join(out) + "\n"


def render_postmortem(inv, resolution: dict) -> str:
    """Draft a postmortem. Timeline and durations are computed; judgement is left to the owner."""
    a = inv.alert
    resolved = parse_time(resolution["resolved_at"])
    events = [(a.onset_at, "Signal went bad"), (a.fired_at, f"Alert fired: {a.title}"), (resolved, "Resolved")]
    credible_changes = {h.change_id for h in inv.hypotheses if h.change_id and h.band != "low"}
    events += [(c.at, f"{c.kind.capitalize()} {c.id} to {c.service}: {c.summary}")
               for c in inv.changes_considered if c.id in credible_changes]
    firsts = [c.first_seen for c in inv.log_clusters if c.first_seen]
    if firsts:
        events.append((min(firsts), "First matching error in the logs"))
    events += [(parse_time(x["at"]), f"{x.get('actor', 'someone')}: {x['action']}") for x in resolution.get("actions", [])]
    events.sort(key=lambda e: e[0])

    confirmed = resolution.get("confirmed_cause", {})
    rank = next((i for i, h in enumerate(inv.hypotheses, start=1) if _matches(h, confirmed)), None)
    ranking = (f"The agent ranked the confirmed cause #{rank} of {len(inv.hypotheses)}." if rank
               else "The confirmed cause was not among the agent's hypotheses.")

    out = [
        f"# Postmortem draft: {a.title}",
        "",
        "> Draft generated from incident data. Timeline and durations are computed. "
        "Sections marked TODO need the incident owner.",
        "",
        "## Summary",
        "",
        f"- **Service:** {a.service}",
        f"- **Severity:** {a.severity}",
        f"- **Duration:** {_minutes(a.onset_at, resolved)} ({fmt_time(a.onset_at)} to {fmt_time(resolved)})",
        f"- **Time to detect:** {_minutes(a.onset_at, a.fired_at)}",
        f"- **Time to mitigate:** {_minutes(a.fired_at, resolved)}",
        f"- **Impact:** {resolution.get('impact', 'TODO')}",
        "",
        "## Confirmed cause",
        "",
        f"{confirmed.get('description', 'TODO: not yet confirmed.')}",
        "",
        ranking,
        "",
        "## Timeline",
        "",
        "| Time (UTC) | Event |",
        "|---|---|",
    ]
    out += [f"| {fmt_time(at).replace(' UTC', '')} | {text} |" for at, text in events]
    out += [
        "",
        "## Contributing factors",
        "",
        "TODO: why did this reach production, and why did it take this long to detect?",
        "",
        "## What went well",
        "",
        "TODO",
        "",
        "## Action items",
        "",
        "| Action | Owner | Due |",
        "|---|---|---|",
        "| TODO | | |",
    ]
    return "\n".join(out) + "\n"


def _matches(hyp, confirmed: dict) -> bool:
    if confirmed.get("kind") == "change":
        return hyp.kind == "change" and hyp.change_id == confirmed.get("change_id")
    return hyp.kind == confirmed.get("kind")
