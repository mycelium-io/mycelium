# Dissent Map — Demo Runbook

**Hackathon scenario:** A critical security vulnerability has been discovered in production. Four
autonomous agents must agree on a response plan — but their constraints are mutually exclusive.
They hit genuine impasse. A human operator reviews the structured dissent artifact, writes a
ruling, and a second session converges in minutes.

**Story arc:** structured impasse → dissent artifact → human ruling → session 2 consensus → plan

---

## Prerequisites

```bash
# Stack running (backend + AgensGraph + frontend)
mycelium install   # or docker compose ... --profile cfn up -d

# Four terminal windows (one per agent), plus one operator terminal
# LLM model set:
mycelium config set llm.model "anthropic/claude-sonnet-4-6"
mycelium config apply
```

---

## Act 1 — Setup (operator)

```bash
# Create the demo room
mycelium room create dissent-map-demo
mycelium room use dissent-map-demo

# Verify room structure
ls .mycelium/rooms/dissent-map-demo/
# decisions/  status/  context/  work/  log/
```

Write shared context so every agent starts from the same facts:

```bash
mycelium memory set context/incident \
  "CVE-2026-9901: critical RCE in auth-service v2.3.1. Exploited in the wild. CVSS 9.8." \
  --handle operator

mycelium memory set context/constraints \
  "SLA breach if service is unavailable >5 min. Patch available but untested at scale. Forensic snapshot takes ~20 min." \
  --handle operator
```

---

## Act 2 — Session 1: negotiation hits impasse

### Start the session (operator)

```bash
mycelium session create --room dissent-map-demo
# Prints session ID — note it for agents
```

### Agents join (four terminals)

```bash
# Terminal 1 — SRE agent
mycelium session join -H sre-agent \
  -m "Roll back or patch now. Hard constraint: no additional outage beyond 5 minutes." \
  --room dissent-map-demo

# Terminal 2 — SecOps agent
mycelium session join -H secops-agent \
  -m "Forensics snapshot required before any prod change. No deploy until snapshot completes (~20 min)." \
  --room dissent-map-demo

# Terminal 3 — PM agent
mycelium session join -H pm-agent \
  -m "Protect the Friday feature launch. SLA breach in 2 hours if we delay further." \
  --room dissent-map-demo

# Terminal 4 — Engineering Lead
mycelium session join -H eng-lead \
  -m "Fix-forward only — won't ship without integration tests passing. Rollback breaks the migration." \
  --room dissent-map-demo
```

### Agents negotiate (loop in each terminal)

```bash
# Each agent runs this loop:
while true; do
  mycelium session await -H <handle> --room dissent-map-demo
  # Read the tick, then respond:
  mycelium negotiate respond --room dissent-map-demo -H <handle> \
    --action counter_offer \
    --offer "deploy_window=48h,forensics=parallel"
done
```

**What to show:** agents proposing, counter-offering, reaching the round limit. The CE exhausts
the budget and posts `coordination_consensus` with `broken: true`.

### `session await` returns impasse (each agent terminal)

```bash
# Output from session await:
{
  "type": "consensus",
  "broken": true,
  "plan": "Negotiation ended: timeout",
  "dissent_file": "decisions/unresolved-tensions.md",
  ...
}
```

**Point out:** `dissent_file` is set — the CE compiled the artifact *before* posting this
message. Agents are told not to restart in plain chat.

---

## Act 3 — Operator reviews the dissent artifact

### CLI path

```bash
mycelium memory get decisions/unresolved-tensions --room dissent-map-demo
```

Shows structured markdown: per-agent last positions, blocking pattern, recommended questions.

### UI path

Open the frontend → navigate to `dissent-map-demo` → select the session.

The **IMPASSE** banner appears (yellow). Below it:

- The dissent artifact path and CLI read command
- A "Record ruling" textarea

---

## Act 4 — Human writes the ruling

### CLI

```bash
mycelium memory set decisions/human-ruling \
  "Ship security patch in 24h under a 3-minute maintenance window. SecOps forensics snapshot runs in parallel, not blocking. PM feature launch deferred 48h max. Eng-lead: integration tests must pass in staging before prod push." \
  --handle operator --room dissent-map-demo
```

### UI

Type the ruling text in the textarea → click **Record ruling**. The UI confirms save to
`decisions/human-ruling`.

---

## Act 5 — Session 2: negotiation converges

### Operator starts session 2

```bash
mycelium session create --room dissent-map-demo
```

### Agents join with ruling in context

**Option A — embed in opening intent (quick):**

```bash
RULING=$(mycelium memory get decisions/human-ruling --room dissent-map-demo)

mycelium session join -H sre-agent \
  -m "Ruling received: $RULING. I accept the 24h window with the parallel forensics approach." \
  --room dissent-map-demo

# Repeat for each agent, tailoring their opening to the ruling
```

**Option B — shared context file (all agents see the same ruling):**

```bash
mycelium memory get decisions/human-ruling --room dissent-map-demo > /tmp/ruling.md

# Each agent:
mycelium session join -H <handle> \
  -m "<brief position acknowledging ruling>" \
  --context-files /tmp/ruling.md \
  --room dissent-map-demo
```

### Session 2 converges

With the ruling constraining the option space, agents converge in 1–3 rounds. The CE compiles
a shared plan:

```bash
mycelium plan tasks --room dissent-map-demo
```

Expected output:

```
dissent-map-demo plan tasks
─────────────────────────────────
[ ] Ship security patch within 24h maintenance window
[ ] SecOps: run forensics snapshot in parallel (non-blocking)
[ ] PM: defer Friday launch by 48h max
[ ] Eng-lead: integration tests must pass in staging before prod push
```

**Show:** the plan came from the agents, constrained by the human ruling — not a fake consensus.

---

## What to highlight in the demo

| Before (baseline) | After (dissent map) |
|---|---|
| Impasse → agents re-debate in plain chat | Impasse → structured artifact written before consensus message |
| Human reads raw negotiation logs | Human reads per-agent positions + blocking pattern + recommended questions |
| Session 2 replays session 1 | Session 2 opens with ruling already in scope; converges in 1–3 rounds |
| No paper trail | `decisions/unresolved-tensions.md` + `decisions/human-ruling.md` in version-controlled room |

---

## Troubleshooting

**Agents agree too quickly (no impasse):**
Use tighter constraints — e.g., set `issue_options` to `["rollback", "patch"]` only and have
SecOps hard-reject everything except forensics-first. Or reduce the round budget:
`mycelium config set cfn.retry_max_attempts 1`.

**Dissent file not written:**
Check that the backend is on the `hackathon_mycelium_dissent` branch. Verify with:
```bash
mycelium memory ls decisions --room dissent-map-demo
```
Should show `unresolved-tensions.md` after a broken session ends.

**Session 2 agents still re-debate:**
Ensure they're reading the ruling before joining (`mycelium memory get decisions/human-ruling`)
or using `--context-files`. The operator can also narrate the ruling in the session create step.

---

## Success criteria

- [ ] Dissent file appears at `decisions/unresolved-tensions.md` after session 1 impasse
- [ ] `dissent_file` is set on the `session await` consensus JSON output
- [ ] UI shows IMPASSE banner (yellow) with dissent path and ruling form
- [ ] Human ruling saved to `decisions/human-ruling.md` via UI or CLI
- [ ] Session 2 opening positions reference the ruling
- [ ] Session 2 reaches consensus; `plan/tasks.md` reflects the human-constrained agreement
