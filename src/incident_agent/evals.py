"""Score the agent on incidents whose cause is known.

The number to watch is the false blame rate: how often the agent calls a
change the likely cause when it was not. Sending an on-call engineer
to roll back an innocent deploy costs more than saying "not sure".
"""
from __future__ import annotations

from pathlib import Path

from .pipeline import investigate
from .render import _matches
from .sources import IncidentFixture


def evaluate(incidents_dir, dependencies: dict, runbooks: list, make_llm=None) -> dict:
    rows = []
    for directory in sorted(Path(incidents_dir).iterdir()):
        if not (directory / "truth.json").exists():
            continue
        fx = IncidentFixture(directory)
        inv = investigate(fx.alert, fx.changes(fx.alert.onset_at.replace(year=1970), fx.alert.onset_at),
                          fx.log_text, dependencies, runbooks, llm=make_llm() if make_llm else None)
        truth = fx.truth["cause"]
        top = inv.hypotheses[0] if inv.hypotheses else None
        rank = next((i for i, h in enumerate(inv.hypotheses, start=1) if _matches(h, truth)), None)
        unknown = truth["kind"] == "none"
        rows.append({
            "incident": fx.id,
            "truth": truth.get("change_id") or truth["kind"],
            "verdict": inv.verdict,
            "top": f"{top.kind}:{top.change_id or ''} {top.score:.2f}" if top else "-",
            "rank_of_truth": rank,
            "top1": (inv.verdict == "no_clear_cause") if unknown else rank == 1,
            "top3": (inv.verdict == "no_clear_cause") if unknown else (rank is not None and rank <= 3),
            "false_blame": bool(top and inv.verdict == "likely_cause" and top.kind == "change"
                                and not _matches(top, truth)),
            "runbook_ok": (not fx.truth.get("runbook")) or
                          (bool(inv.runbooks) and inv.runbooks[0].id == fx.truth["runbook"]),
            "model_rejections": len(inv.model.get("rejected", [])),
        })
    n = len(rows) or 1
    return {
        "rows": rows,
        "metrics": {
            "incidents": len(rows),
            "top1_accuracy": round(sum(r["top1"] for r in rows) / n, 3),
            "top3_accuracy": round(sum(r["top3"] for r in rows) / n, 3),
            "false_blame_rate": round(sum(r["false_blame"] for r in rows) / n, 3),
            "runbook_top1_accuracy": round(sum(r["runbook_ok"] for r in rows) / n, 3),
        },
    }


def render_eval(result: dict) -> str:
    out = ["| Incident | True cause | Verdict | Top hypothesis | Rank of truth | False blame | Runbook |",
           "|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        out.append(f"| {r['incident']} | {r['truth']} | {r['verdict']} | {r['top']} | "
                   f"{r['rank_of_truth'] or '-'} | {'YES' if r['false_blame'] else 'no'} | "
                   f"{'ok' if r['runbook_ok'] else 'wrong'} |")
    out.append("")
    out += [f"- {name}: {value if name == 'incidents' else f'{value:.0%}'}"
            for name, value in result["metrics"].items()]
    return "\n".join(out) + "\n"
