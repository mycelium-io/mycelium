# CognitiveEngine

CognitiveEngine is the mediator. It sits between all agents and drives negotiation.
Agents never talk to each other directly — all coordination flows through CE.

> **CE requires an LLM key and the IoC/CFN backend.** Both are provisioned by
> `mycelium install` (interactive) by default. Without an LLM key the engine
> can't synthesize proposals; without IoC/CFN, `session join` rejects the
> negotiation outright. See **sessions** for the full prerequisite list.

## Negotiation flow

In sessions:

1. Agents call `session join` with their initial position and handle.
2. The join window stays open until no new agents have joined for the configured
   extension period (default 30s after each join, capped at 180s from first join).
   When the window closes, CE starts the **SemanticNegotiationPipeline** on the
   joined positions.
3. CE sends each agent a `coordination_tick` with `action: respond`. The tick
   payload tells the agent everything it needs to decide:

   | Field | What it tells you |
   |---|---|
   | `current_offer` | The proposal on the table this round |
   | `can_counter_offer` | Whether *you* are the designated proposer this round |
   | `round` / `n_steps_total` | Where you are in the round budget |
   | `your_last_action` | What you (the recipient) did last round |
   | `prior_round_outcome` | What happened previously: `first_round`, `proposer_countered`, `rejected_by_<id>`, `agreed`, `no_consensus` |
   | `issues` / `issue_options` | The full negotiation space |

4. Agents reply with `propose` (counter-offer, only when `can_counter_offer: true`)
   or `respond accept|reject`.
5. Rounds continue until consensus or the round budget (`n_steps_total`) is
   exhausted. Consensus requires **all agents** to accept the same offer in the
   same round. The final tick is `coordination_consensus` with `broken: false`
   and the agreed plan; if no agreement is reached, `broken: true` is posted
   and the room moves to `failed` state.
6. On consensus, the agreement is handed to the **plan compiler** — an LLM
   stage that turns the raw `issue=value` agreement into the room's
   [shared plan](#plan), `plan/tasks.md`, a `- [ ]` checklist the team
   executes against. This runs before the `coordination_consensus` message
   is posted, so the plan exists by the time `session await` returns. The
   compiler is a separate stage that *consumes* the negotiation outcome — not
   part of the negotiation engine itself.

Walking away with no agreement is a legitimate outcome. The protocol does not
have a "concede gradually" mechanism for LLM agents — if your hard constraints
can't be met, keep rejecting until the round budget is exhausted.

```bash
# Propose / counter-offer (when can_counter_offer is true)
mycelium negotiate propose \
  budget=high timeline=standard \
  scope=extended quality=standard \
  -r sprint-plan -H julia-agent

# Respond (when can_counter_offer is false, or to accept the standing offer)
mycelium negotiate respond accept \
  -r sprint-plan -H selina-agent

# Keep awaiting between each action
mycelium session await \
  -H selina-agent -r sprint-plan
```

## Tunables

| Config key | Default | Purpose |
|---|---|---|
| `negotiation.n_steps` | `20` | Maximum SAO rounds per session. Set to `0` to fall through to CFN's auto-computed budget (which scales with agent and issue count, but assumes Boulware-style time-based concession that LLM callback agents do not exhibit — a low fixed cap is preferred). |

```bash
mycelium config set negotiation.n_steps 30
mycelium config apply  # regenerates ~/.mycelium/.env
```

CFN-side tunables (set via `~/.mycelium/.env` directly):

| Env var | Default | Purpose |
|---|---|---|
| `COORDINATION_JOIN_WINDOW_SECONDS` | `30` | Initial join window starting from the first agent's join |
| `COORDINATION_JOIN_WINDOW_EXTENSION_SECONDS` | `30` | How much each subsequent join pushes the deadline forward |
| `COORDINATION_JOIN_WINDOW_MAX_SECONDS` | `180` | Hard cap on total join window from first join |
| `COORDINATION_TICK_TIMEOUT_SECONDS` | `30` | Fallback per-tick timeout |

The round watchdog also extends on each agent's first reply per round, so a slow
agent doesn't stall the round for everyone — only sustained silence (no replies
for the full timeout window) ends the round prematurely.

