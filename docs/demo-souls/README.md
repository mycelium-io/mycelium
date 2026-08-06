# Demo agent SOUL.md files

Identity documents for the four dissent-map demo personas. Copy the relevant file to each
agent's OpenClaw workspace as `SOUL.md`.

**Scenario:** A checkout bug is found 24 hours before a major Friday launch. Ship or slip?

| File | Handle | Hard constraint |
|---|---|---|
| `pm-agent.md` | `pm-agent` | Friday launch is committed; slipping triggers SLA penalty + cancels paid marketing campaign |
| `eng-lead.md` | `eng-lead` | Will not ship known data corruption; staging validation required |
| `sre-agent.md` | `sre-agent` | Must be reversible in under 2 minutes; needs a kill switch on checkout |
| `secops-agent.md` | `secops-agent` | Needs exploitability review before release; discount-code bugs are a known attack surface |

## What goes here vs. the join message

These files define **character**: expertise, reasoning style, and what each agent is
skeptical of. They do not encode a position on this specific launch.

The scenario brief (bug description, Friday date, SLA clause, marketing campaign details)
goes in the `session join -m "..."` opening position. See `demo-agent.py` for the exact
intent strings used by the simulator.

## The human ruling

After session 1 ends in impasse, write your ruling into the UI. A ruling that works well:

> Ship Friday with checkout behind a feature flag. Run exploitability review in parallel
> (2 hours). If review flags an issue or error rate exceeds 1%, pull the flag immediately.
> Staging run can proceed against the fix branch concurrently — if it passes before EOD
> Friday, deploy the fix and remove the flag.

This gives pm-agent and sre-agent what they need (ship, kill switch), gives secops-agent
the review window, and gives eng-lead a path to the clean fix without blocking the launch.

## Setup

```bash
# Install the Mycelium OpenClaw adapter (once per machine)
mycelium adapter add openclaw

# Allowlist the mycelium binary for each agent
openclaw approvals allowlist add --agent sre-agent    "$(which mycelium)"
openclaw approvals allowlist add --agent secops-agent "$(which mycelium)"
openclaw approvals allowlist add --agent pm-agent     "$(which mycelium)"
openclaw approvals allowlist add --agent eng-lead     "$(which mycelium)"

# Set the agent handle in each agent's environment
export MYCELIUM_AGENT_HANDLE=sre-agent   # per agent
```

Then copy the matching SOUL.md to each agent workspace and restart the gateway.
