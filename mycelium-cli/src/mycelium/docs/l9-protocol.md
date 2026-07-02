# L9 Protocol

L9 is the epistemic protocol layer of the Internet of Cognition (IOC) initiative
([ioc-protocols-models](https://github.com/outshift-open/ioc-protocols-models)).
It gives multi-agent exchanges a shared envelope format — typed messages with
causal links, episode identity, and epistemic annotations — so that *how* a team
reached an agreement is as inspectable as the agreement itself. Mycelium wraps
its coordination messages in L9 envelopes, lets agents attach confidence and
evidence to their replies, and scores every consensus for quality.

> Everything on this page is **additive and optional**. Agents that ignore the
> `l9` key and never send epistemic fields participate exactly as before.

## Envelopes and episodes

Every negotiation session is an L9 **episode**, identified by the URN
`urn:ioc:mycelium:episode:{room}:{session_short_id}` with topic
`urn:concept:mycelium:{room}`. Coordination messages carry an `l9` key inside
their content JSON:

| Message | L9 kind | Subkind |
|---|---|---|
| `coordination_tick` | `exchange` | — |
| `coordination_consensus` (agreement) | `commit` | `converged` |
| `coordination_consensus` (no agreement) | `commit` | `abort` |

Each envelope has a UUID message id and causal `parents`: a tick parents the
agent's prior reply, reply envelopes (synthesized by the backend from your
`propose`/`respond` calls) parent the tick they answer, and the consensus
parents the final replies. The result is a causal chain from opening positions
to outcome. Subkind vocabulary follows the Go CFN's table — `commit` also
allows `resolved`, and other kinds (`intent`, `knowledge`, `contingency`) are
used for CFN-side traffic like team priors below.

## Epistemic reply fields

Agents may annotate any `propose` or `respond` with how sure they are and why.
All fields are optional:

| Field | Type | Meaning |
|---|---|---|
| `confidence` | 0–1 | How confident you are in your position |
| `evidence` | list of strings | Concrete support for the position |
| `reasoning` | string | Free-form rationale |
| `deferred_to` | agent handle | On an accept: you yielded to this agent without being persuaded |

```bash
# Propose with epistemic annotations
mycelium negotiate propose budget=high \
  --confidence 0.8 \
  --evidence "staging p99 data" \
  --reasoning "high budget is the only option that meets the latency target"

# Accept, but flag that you deferred rather than agreed
mycelium negotiate respond accept --confidence 0.4 --defer-to julia-agent
```

Use `--defer-to` honestly: it doesn't change the negotiation outcome, but it
feeds the social-compliance metric below, and that's the whole point — a
consensus where half the team deferred should *look* weaker than one where
everyone converged.

## Consensus quality metrics

When at least two agents report confidence (and at most one stays silent), the
backend attaches a `metrics` object to the `coordination_consensus` payload:

| Metric | Meaning | Read it as |
|---|---|---|
| `mpc` | Mean final confidence | How sure the team is, on average |
| `gar` | Genuine agreement ratio — fraction whose confidence moved *toward* the outcome vs their first stated confidence | How much of the agreement was earned by the negotiation |
| `scr` | Social compliance ratio — fraction of final accepts carrying `deferred_to` | How much of the agreement is deference |
| `provenance_weight` | `(1 - scr) * gar` | Single trust score for the consensus |

High `mpc` with low `gar` means the team agreed from the start; high `scr`
means agents caved. Metrics are rendered in the UI (session banner and cards)
and in `mycelium watch` output. They are interim: they move to the Cognition
Engine once it computes them natively.

## Episode records

On consensus, the full causally-linked envelope record is written to room
memory at `log/episodes/{session_short_id}.md` — a markdown summary plus a fenced JSONL
block of every envelope in the episode. Like any room memory it's
git-shareable and searchable via the normal memory index.

## Team priors

With `L9_CFN_ENABLED=true` and a knowledge CE registered with the CFN, Mycelium
queries the CFN knowledge fabric (`kind=knowledge, subkind=query`) at session
start and injects a `team_prior` into every tick — `{confidence,
provenance_weight, episode_count}` summarizing how this team has agreed on
this topic before. After a converged consensus it writes the agreement back
(`kind=knowledge, subkind=feedback`), so the prior improves over time. Both
directions are fail-soft: if the fabric is unreachable, negotiation proceeds
without priors.

> Team priors are dark-launched — off unless `L9_CFN_ENABLED=true` is set
> *and* a knowledge CE is registered with the CFN.

## The CFN service

Negotiation and L9 routing are served by the CFN
([ioc-cfn-svc](https://github.com/outshift-open/ioc-cfn-svc)) via its
semantic-alignment API. The terminal agreement arrives as a `final_result`
SSTP envelope, responses carry trace/meta/shared-memory extras, and
agreements are auto-persisted to CFN shared memory (surfaced as
`cfn_persisted` on the consensus payload).
