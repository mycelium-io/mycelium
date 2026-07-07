# L9 Protocol

Every negotiation ends in "accept," but an accept can mean *"you convinced
me"* or *"fine, whatever, let's move on."* If you can't tell those apart, you
can't tell a real team decision from one agent steamrolling the rest, and the
plan your agents execute inherits that blind spot.

L9 (the epistemic layer of the [Internet of
Cognition](https://github.com/outshift-open/ioc-protocols-models)) fixes this
by making *how* the team decided as inspectable as *what* it decided. Agents
say how sure they are and why; every consensus gets a quality score; every
negotiation leaves a causal paper trail.

> Everything on this page is **additive and optional**. Agents that never send
> epistemic fields participate exactly as before.

## Say how sure you are

Any `propose` or `respond` can carry your epistemic state:

```bash
mycelium negotiate propose budget=high \
  --confidence 0.8 \
  --evidence "staging p99 data" \
  --reasoning "only option that meets the latency target"

# Accepting just to move on? Say so:
mycelium negotiate respond accept --confidence 0.4 --defer-to julia-agent
```

- `--confidence` (0–1): how sure you are of your position
- `--evidence` (repeatable): what it rests on, such as file paths, memory keys, claims
- `--reasoning`: the one-liner rationale
- `--defer-to <handle>`: on an accept, *you yielded without being persuaded*

Defer honestly. It doesn't change the outcome; it changes how much the
outcome can be trusted, which is the point. A dishonest "accept" corrupts the
team's shared memory; an honest deferral just marks the consensus as thinner.

## Read the quality of a consensus

When enough agents report confidence, the consensus carries a `metrics` score
(shown in the session view, the cards, and `mycelium watch`):

| Metric | Read it as |
|---|---|
| `mpc` | How sure the team is, on average |
| `gar` | Who was actually persuaded: did confidence move *toward* the outcome? |
| `scr` | Who just went along: fraction of accepts that were deferrals |
| `provenance_weight` | The single trust score: `(1 - scr) * gar` |

Two negotiations can both end `accept × 3` and look nothing alike: MPC 0.85
with SCR 0 is a genuine team decision; MPC 0.5 with SCR 0.67 is one agent
dragging two others. Now you can see the difference, and so can the agents
reading the room's history.

## Team priors: start from what the team already learned

With the CFN knowledge fabric enabled, each session opens with the team's
earned confidence on this topic: a `team_prior` in every tick
(`{confidence, provenance_weight, episode_count}`), written back after each
converged consensus so it improves over time. Agents are instructed to form
their own view first, then weigh the prior: a starting point, not an answer.

> Off by default: requires `L9_CFN_ENABLED=true` *and* a knowledge CE
> registered with the CFN. Fail-soft in both directions: no fabric, no
> priors, negotiation proceeds normally.

## The paper trail

Every negotiation is an L9 **episode**: ticks, replies, and the closing
commit, causally linked (each message cites its `parents`) from opening
positions to outcome. On consensus the full record lands in room memory at
`log/episodes/{session_short_id}.md`, git-shareable and searchable like any
memory, so "why did we decide this?" has an answer months later.

## Under the hood

Coordination messages carry an `l9` envelope inside their content JSON: ticks
are `exchange`, agreement commits as `converged`, failure as `abort`, on the
episode URN `urn:ioc:mycelium:episode:{room}:{session_short_id}`. Reply
envelopes are synthesized by the backend; agents never need to speak L9
themselves. Negotiation and L9 routing are served by the CFN
([ioc-cfn-svc](https://github.com/outshift-open/ioc-cfn-svc)) via its
semantic-alignment API; agreements are auto-persisted to CFN shared memory
(`cfn_persisted` on the consensus payload). The quality metrics are computed
by Mycelium for now and move to the Cognition Engine when it computes them
natively.
