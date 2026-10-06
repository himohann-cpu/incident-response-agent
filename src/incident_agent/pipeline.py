"""The investigation, start to finish.

Phase 1 (code): gather evidence, rank causes, match runbooks, pick the verdict.
Phase 2 (model, optional): explain the ranking. If the model is missing, slow,
wrong or over budget, phase 1's output stands on its own.
"""
from __future__ import annotations

from datetime import timedelta

from . import llm as llm_module
from .correlate import band, score_changes
from .logs import cluster_logs
from .models import Evidence, Investigation, ProposedAction, fmt_time
from .rules import rule_hypotheses
from .runbooks import match_runbooks

MAX_HYPOTHESES = 5
CLEAR_LEAD = 0.1   # how far ahead the top hypothesis must be to be called the likely cause
CORROBORATION_BONUS = 0.15
NEXT_CHECK = {
    "change": "Compare the error rate just before and just after this change went out.",
    "dependency": "Check the dependency's status page and its error rate from another client.",
    "certificate": "Inspect the certificate's expiry date on the failing endpoint.",
    "resource": "Look at memory and disk graphs for the hour before the onset.",
    "quota": "Check current usage against the provider's quota or rate limit.",
    "database": "List long-running queries and current locks.",
    "dns": "Resolve the failing host name from inside the cluster.",
}
CHANGE_ACTIONS = {
    "config": ("Revert config change {ref} on {service}", "", "revert_config", "on-call engineer"),
    "flag": ("Turn off the flag changed in {ref} on {service}", "", "revert_config", "on-call engineer"),
    "migration": ("Stop or revert migration {ref} on {service}", "", "stop_migration", "database owner"),
}
ACTIONS = {
    "change": ("Roll back {service} to the version before {ref}", "rollback {service} --to-before {ref}",
               "rollback_deploy", "on-call engineer"),
    "dependency": ("Page the owner of the failing dependency and enable degraded mode if one exists",
                   "", "page_owner", "incident commander"),
    "certificate": ("Renew and redeploy the expired certificate", "", "rotate_certificate", "service owner"),
    "resource": ("Restart the affected instances to restore service while the cause is confirmed",
                 "", "restart_service", "on-call engineer"),
    "database": ("Stop the blocking query or migration", "", "stop_migration", "database owner"),
}


def investigate(alert, changes, log_text, dependencies=None, runbooks=None, llm=None,
                window_hours: int = 24) -> Investigation:
    dependencies = dependencies or {}
    window_start = alert.onset_at - timedelta(hours=window_hours)
    considered = [c for c in changes if window_start <= c.at <= alert.onset_at]
    clusters = cluster_logs(log_text)

    # ---- evidence: every fact gets an id the model must cite
    evidence = [Evidence("E1", "alert",
                         f"{alert.title} on {alert.service} (severity {alert.severity}); signal went bad at "
                         f"{fmt_time(alert.onset_at)}, alert fired at {fmt_time(alert.fired_at)}. {alert.detail}".strip())]
    change_evidence, cluster_evidence = {}, {}
    for change in considered:
        eid = f"E{len(evidence) + 1}"
        change_evidence[change.id] = eid
        files = f" Files: {', '.join(change.files[:6])}." if change.files else ""
        evidence.append(Evidence(eid, "change", f"{change.kind} {change.id} to {change.service} at "
                                                f"{fmt_time(change.at)} by {change.author or 'unknown'}: "
                                                f"{change.summary}.{files}"))
    for cluster in clusters:
        eid = f"E{len(evidence) + 1}"
        cluster_evidence[cluster.signature] = eid
        first = f", first seen {fmt_time(cluster.first_seen)}" if cluster.first_seen else ""
        evidence.append(Evidence(eid, "log", f"{cluster.count} error lines ({cluster.share:.0%} of errors{first}): "
                                             f"{cluster.example}"))
    upstream = dependencies.get(alert.service, [])
    if upstream:
        evidence.append(Evidence(f"E{len(evidence) + 1}", "topology",
                                 f"{alert.service} depends on: {', '.join(upstream)}"))

    # ---- hypotheses: changes and non-change rules compete in one ranking
    hypotheses = score_changes(alert, considered, clusters, dependencies)
    changes_by_id = {c.id: c for c in considered}
    for hyp in hypotheses:
        hyp.evidence = ["E1", change_evidence[hyp.change_id]]
        for cluster in clusters:
            if any(f in cluster.signature or f in cluster.example
                   for f in hyp.factors.get("files_seen_in_errors", [])):
                hyp.evidence.append(cluster_evidence[cluster.signature])
    for symptom, matched in rule_hypotheses(clusters):
        symptom.evidence = ["E1"] + [cluster_evidence[c.signature] for c in matched]
        # A symptom says what is failing; a change may say why. When they fit
        # together, the change is corroborated rather than competing with it.
        for hyp in hypotheses:
            if hyp.kind == "change" and _corroborates(symptom, changes_by_id[hyp.change_id], alert):
                hyp.score = round(min(0.95, hyp.score + CORROBORATION_BONUS), 3)
                hyp.band = band(hyp.score)
                hyp.factors["corroborated_by"] = symptom.title
                hyp.evidence += [e for e in symptom.evidence if e not in hyp.evidence]
                hyp.runbook_tags = hyp.runbook_tags + symptom.runbook_tags  # the symptom's runbook is the specific one
        hypotheses.append(symptom)
    hypotheses = sorted(hypotheses, key=lambda h: -h.score)[:MAX_HYPOTHESES]
    for rank, hyp in enumerate(hypotheses, start=1):
        hyp.id = f"H{rank}"
        hyp.evidence = sorted(set(hyp.evidence), key=lambda e: int(e[1:]))
        hyp.next_check = NEXT_CHECK.get(hyp.kind, "")
        hyp.narrative = _template_narrative(hyp)

    # ---- verdict
    credible = [h for h in hypotheses if h.band != "low"]
    if not credible:
        verdict = "no_clear_cause"
    elif credible[0].band == "high" and (len(hypotheses) == 1 or
                                         credible[0].score - hypotheses[1].score >= CLEAR_LEAD):
        verdict = "likely_cause"
    else:
        verdict = "possible_causes"

    matches = match_runbooks(runbooks or [], alert.service, credible) if credible else \
        [m for m in match_runbooks(runbooks or [], alert.service, [_triage_stub()])]

    actions = []
    for hyp in [h for h in credible if h.band == "high"][:2]:  # act only on strong evidence
        if hyp.kind in ACTIONS:
            change = changes_by_id.get(hyp.change_id)
            text, command, action_class, approver = CHANGE_ACTIONS.get(change.kind if change else "", ACTIONS[hyp.kind])
            fill = {"service": change.service if change else alert.service,
                    "ref": (change.ref or change.id) if change else ""}
            actions.append(ProposedAction(action=f"{text.format(**fill)} (for {hyp.id})",
                                          command=command.format(**fill), action_class=action_class,
                                          needs=approver))

    investigation = Investigation(
        alert=alert, evidence=evidence, changes_considered=considered, log_clusters=clusters,
        hypotheses=hypotheses, verdict=verdict, runbooks=matches, actions=actions,
        status_update=_template_status(alert, hypotheses, verdict),
        model={"used": False, "reason": "no model configured"},
    )
    if llm is not None and hypotheses:
        _model_phase(investigation, llm)
    return investigation


def _corroborates(symptom, change, alert) -> bool:
    """Does this symptom make this change a more likely cause?"""
    if symptom.kind == "database":
        return change.kind == "migration"
    if symptom.kind == "resource":
        return change.service == alert.service
    if symptom.kind == "dependency":
        return change.service != alert.service and any(change.service in tag for tag in symptom.runbook_tags)
    return False


def _model_phase(investigation, llm) -> None:
    try:
        result = llm.complete(llm_module.SYSTEM_PROMPT, llm_module.build_prompt(investigation))
    except Exception as error:  # any failure here must not lose the investigation
        investigation.model = {"used": False, "reason": f"model call failed: {type(error).__name__}: {error}"[:300]}
        return
    rejected = llm_module.apply_model_output(investigation, result.text)
    investigation.model = {
        "used": True, "model": result.model, "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens, "cost_usd": llm_module.cost_usd(result), "rejected": rejected,
    }


def _template_narrative(hyp) -> str:
    f = hyp.factors
    if hyp.kind == "change":
        parts = [f"It went out {f['minutes_before_onset']} minutes before the signal went bad."]
        parts.append({1.0: "It changed the alerting service itself.", 0.7: "It changed a direct dependency.",
                      0.3: "It changed a dependency two hops away.", 0.0: "It changed an unrelated service."
                      }[f["topology"]])
        if f.get("files_seen_in_errors"):
            parts.append(f"Files it changed appear in the errors: {', '.join(f['files_seen_in_errors'])}.")
        else:
            parts.append("Nothing in the errors points at the files it changed.")
        if f.get("corroborated_by"):
            parts.append(f"The symptom fits this kind of change: {f['corroborated_by'].lower()}.")
        return " ".join(parts)
    return (f"{f['share_of_errors']:.0%} of the error lines match this pattern, "
            f"across {f['matching_clusters']} distinct signature(s).")


def _template_status(alert, hypotheses, verdict) -> str:
    opening = f"We are investigating: {alert.title} on {alert.service}, since {fmt_time(alert.onset_at)}."
    if verdict == "likely_cause":
        return f"{opening} The likely cause is: {hypotheses[0].title}. We are confirming and preparing mitigation."
    if verdict == "possible_causes":
        return f"{opening} We have {sum(h.band != 'low' for h in hypotheses)} candidate causes and are narrowing them down."
    return f"{opening} We have not identified a cause yet."


def _triage_stub():
    from .models import Hypothesis
    return Hypothesis(id="-", kind="unknown", title="", score=0.5, band="medium", runbook_tags=["triage"])
