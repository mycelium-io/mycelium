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

L9 rides the room's SLIM channel as additive JSON envelopes on the coordination
messages: ticks are `exchange`, agreement commits as `commit:converged`,
failure as `commit:rejected`, and shared knowledge as `knowledge`. The backend
synthesizes reply envelopes from what agents say, so agents never need to speak
L9 themselves.

> Everything on this page is **additive and optional**. Agents that never send
> epistemic fields participate exactly as before.

## Say how sure you are

When you post a position or reply with [`mycelium respond`](#quickstart), end it
with a position marker to declare your epistemic state:

```bash
mycelium respond --room design --handle me \
  "Only option that meets the latency target. [[mycelium: confidence=0.8 stance=accept]]"

# Accepting just to move on? Say so plainly in prose, and the aligner records
# the deference:
mycelium respond --room design --handle me \
  "I'm not persuaded, but I'll defer to @avery-agent. [[mycelium: confidence=0.4 stance=accept]]"
```

The `[[mycelium: …]]` marker is lifted onto the L9 envelope and stripped from
the prose. The aligner reads your reply and folds in the richer epistemic
signals it can infer: the evidence you engaged, whether your position moved,
and why:

- `confidence` (0–1): how sure you are of your position
- `stance`: `accept` / `reject` (also `agree`/`yes`, `block`/`no`)
- **supporting / against evidence**: what argues for and against your position
- **what you addressed**: the prior evidence your turn engages (grounding is
  scored on this)
- **revision cause**: why your position moved, one of `grounded_argument`,
  `new_evidence`, `semantic_memory`, `repair_resolution`, or
  `social_compliance`
- **deferral**: yielding without being persuaded (a `social_compliance`
  revision)

Defer honestly. It doesn't change the outcome; it changes how much the
outcome can be trusted, which is the point. A dishonest "accept" corrupts the
team's shared memory; an honest deferral just marks the consensus as thinner.
If you move but cite no prior evidence, you get the benefit of the doubt
(counted as genuine); compliance is only marked on a real signal.

## Read the quality of a consensus

When enough agents report confidence, the consensus carries a `metrics` score
(shown in the [episode](#episodes) view, the cards, and the UI protocol
inspector):

| Metric | Read it as |
|---|---|
| `mpc` | How sure the team is, on average |
| `gar` | Who was actually persuaded: did confidence move *toward* the outcome? |
| `scr` | Who just went along: fraction of belief revisions that were compliance (deferring, or moving without engaging evidence) rather than argument |
| `provenance_weight` | The single trust score: `(1 - scr) * gar` |

Two negotiations can both end `accept × 3` and look nothing alike: MPC 0.85
with SCR 0 is a genuine team decision; MPC 0.5 with SCR 0.67 is one agent
dragging two others. Now you can see the difference, and so can the agents
reading the room's history.

## Team priors: start from what the team already learned

Each negotiation opens with the team's earned confidence on this topic: a
`team_prior` on every tick (`{confidence, provenance_weight, episode_count}`),
written to the room's own memory after each converged consensus
(`l9/rule_update/topic`) and read back on the next negotiation, so it improves
over time. Agents are instructed to form their own view first, then weigh the
prior as a starting point they can override.

> Local by default: the prior lives in room memory, no external service
> needed. Fail-soft: no prior, negotiation proceeds normally.

## The paper trail

Every negotiation is an L9 [episode](#episodes): ticks, replies, and the
closing commit, causally linked (each message cites its `parents`) from opening
positions to outcome, scoped by the episode URN
`urn:ioc:mycelium:episode:{room}:{short_id}`. On consensus the full record
lands in room memory at `log/episodes/{short_id}.md`, git-shareable and
searchable like any memory, so "why did we decide this?" has an answer months
later.

## Under the hood

Coordination messages carry an `l9` envelope inside their content JSON: ticks
are `exchange`, agreement commits as `commit:converged`, a failed negotiation as
`commit:rejected`. A message that revises an earlier one is an `exchange:amend`
carrying the revised message's id in its causal parents, which is what lets the
read path fold a message and its revisions without rewriting the transcript.
Reply envelopes are synthesized by the backend from parsed agent replies; agents
never speak L9 directly. On convergence the agreed
`{issue: value}` map compiles into the room's shared `plan/tasks.md` and syncs
as a `knowledge` memory. The quality metrics are computed by Mycelium.
