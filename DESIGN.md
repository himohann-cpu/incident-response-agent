# Design: Incident Response Agent

## 1. Problem

The first fifteen minutes of an incident are spent assembling context: which
deploys went out, what the errors have in common, which runbook applies. The
work is mechanical, it happens under pressure, and it is repeated by every
engineer who joins the call.

An agent can do that assembly in seconds. The risk is the obvious one: a
fluent, confident, wrong answer during an outage sends people the wrong way
when time matters most. The most damaging version is **false blame**: telling
on-call that the last deploy caused it, when the real cause is elsewhere.

So the design goal is narrow: shorten the time to a correct first hypothesis,
and never be confidently wrong about what to roll back.

## 2. Principles

1. **Code decides, the model explains.** Evidence, scores, ranking, verdict,
   runbook matches and proposed actions are computed. The model writes prose
   about them.
2. **The brief is complete without the model.** A model outage during an
   incident is likely, since incidents are often correlated. The agent must
   not be one more thing that is down.
3. **Every claim is traceable.** Facts get ids. Model text must cite them.
4. **"Not sure" is a valid result.** There are three verdicts, and two of them
   tell the reader not to act on the top hypothesis alone.
5. **Read-only.** The agent proposes actions and names who must approve them.
   It holds no credentials that could execute one.

## 3. Flow

| Stage | Input | Output | Done by |
|---|---|---|---|
| Intake | Alert | Service, onset time, signal type | Code |
| Collect | Change sources, logs, service map | Changes in the window, error clusters, dependencies | Code |
| Number | All of the above | Evidence list with ids `E1…En` | Code |
| Rank | Evidence | Hypotheses with score, band and factor breakdown | Code |
| Decide | Hypotheses | Verdict | Code |
| Match | Credible hypotheses | Runbooks and proposed actions | Code |
| Explain | Evidence and ranked hypotheses | Explanation per hypothesis, status update | Model |
| Check | Model reply | Accepted text, list of rejections | Code |
| Report | Everything | Incident brief; postmortem draft after resolution | Code |

## 4. Key decisions

### 4.1 Onset time, not alert time

Alerts fire minutes after a signal goes bad. Correlating changes against the
alert time makes a deploy that landed during the degradation look like a
suspect. The agent uses the onset time and ignores any change after it.

### 4.2 Symptoms and causes share one ranking

"The database is refusing queries" and "a migration went out a minute before"
are not rivals. One says what is failing, the other may say why. When a
pattern rule and a change fit together, the change gets a corroboration bonus
and inherits the symptom's evidence and runbook. When a symptom has no
matching change, as with an upstream outage, it stands as the cause and
outranks an unrelated recent deploy.

### 4.3 Decay depends on the signal

Most regressions show within minutes, so suspicion decays with a 45-minute
constant. Memory and disk problems build for hours, so for saturation alerts
the constant is 6 hours. Without this, a leak introduced at 15:20 that kills
pods at 21:40 loses to whatever harmless change went out at 21:15.

### 4.4 Three verdicts

| Verdict | Condition | What the brief does |
|---|---|---|
| `likely_cause` | Top hypothesis is in the high band and leads the next by at least 0.10 | Names it, proposes the action |
| `possible_causes` | At least one credible hypothesis, no clear leader | Lists them, warns not to treat the first as confirmed |
| `no_clear_cause` | Nothing above the low band | Says so, suggests the triage runbook, proposes no action |

Actions are proposed only for high-band hypotheses.

### 4.5 Checks on the model's reply

| Check | On failure |
|---|---|
| Reply is a JSON object | Whole reply dropped |
| Each hypothesis id is one that code ranked | That item dropped |
| Each explanation cites at least one evidence id, and all cited ids exist | That item dropped |
| Proposed order keeps every hypothesis in its band | Order ignored |
| Status update does not say "root cause" unless the verdict is `likely_cause` | Status update dropped |
| Lengths within limits | Truncated |

Dropped items fall back to template text, and the brief lists what was
rejected so reviewers can see how often the model is overruled.

### 4.6 Untrusted input

Log lines, commit messages and ticket text are attacker-writable. They reach
the model only inside a block marked `trust="untrusted"`, and the system
prompt states that its content is data. This is a mitigation, not a
guarantee. The stronger protection is structural: nothing the model says can
change the ranking, the verdict or the proposed actions.

## 5. Autonomy

| Capability | Level | Notes |
|---|---|---|
| Read alerts, changes, logs | Read-only | GitHub adapter issues GET requests only |
| Post the brief | Advise | A human reads it and decides |
| Propose a rollback or revert | Advise | Printed with the approver's role; never executed |
| Execute any action | Not granted | Would need a deterministic post-check and automatic rollback first |

A sensible next step is letting the agent prepare, but not run, the rollback
for `likely_cause` verdicts on stateless services. That should wait for a
measured false-blame rate on real incidents.

## 6. Evaluation

Each sample incident has a `truth.json` naming the real cause and the right
runbook. `incident-agent eval` reports:

| Metric | Meaning |
|---|---|
| `top1_accuracy` | True cause ranked first, or `no_clear_cause` when the truth is "none" |
| `top3_accuracy` | True cause in the top three |
| `false_blame_rate` | Verdict was `likely_cause`, the top hypothesis was a change, and it was wrong |
| `runbook_top1_accuracy` | Correct runbook suggested first |

`--gate` fails the run when the false-blame rate is above zero. CI runs it on
every change, so a tweak to the weights that starts blaming innocent deploys
is caught before it merges.

The sample set deliberately includes cases built to tempt a naive ranker:

| Incident | Trap |
|---|---|
| `03-upstream-outage` | A deploy 19 minutes before an outage it did not cause |
| `05-slow-memory-leak` | The real cause is six hours old; a harmless change is 25 minutes old |
| `07-no-clear-cause` | The only recent deploy is to an unrelated service |
| `08-traffic-surge` | A harmless deploy to the same service 12 minutes before a traffic spike |

## 7. Limits

- **No traffic or metric data.** The agent cannot tell a regression from a
  load spike (`08-traffic-surge` is the known miss). A metric source would add
  a "traffic versus last week" fact and a capacity rule.
- **Log overlap needs paths in the errors.** Stack traces help; a service that
  logs only messages gets no overlap signal and leans on timing.
- **Weights are hand-set.** They should be fitted against real incident
  history once there is enough of it.
- **The service map is a static file.** In practice it should come from a
  service catalog.
- **Pattern rules are a short list.** They cover common failure classes and
  will miss anything unusual.
- **The model clients are untested against live models**, and nothing here
  measures whether model explanations are better than the templates.

## 8. Extending it

| To add | Do this |
|---|---|
| Another change source (deploy system, config service, feature flags) | A class with `changes(since, until) -> list[Change]` |
| A log store | A class with `error_lines(service, since, until) -> str` |
| A new non-change cause | One entry in `RULES` in `rules.py`, and a runbook with matching tags |
| A runbook | A Markdown file in `runbooks/` with the header shown in `runbooks.py` |
| An incident for the eval | A folder with `alert.json`, `changes.json`, `logs.txt`, `truth.json` |
