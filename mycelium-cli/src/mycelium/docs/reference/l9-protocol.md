# L9 Protocol

L9 is a message format for agents coordinating with each other, from the
[Internet of Cognition](https://outshift.cisco.com/blog/ai-ml/mind-the-semantic-gap-osi-model)
work. In Mycelium it's extra data the hub attaches to coordination messages
(the turns of a flow or negotiation, and their outcome), so a negotiation can
be scored and replayed later.

Agents never build L9 messages themselves. They write prose, optionally with a
`[[mycelium: …]]` marker at the end, and the hub turns that into L9. An agent
that never writes a marker takes part as normal.

## Markers

A marker is a short tag at the end of a reply. The hub reads it and removes it
from what gets posted.

| Marker | Used for |
|---|---|
| `[[mycelium: stance=accept]]` / `stance=reject` | Approving or rejecting, in a flow step or a negotiation. `agree` and `yes` also mean accept; `no` and `block` also mean reject (this `block` has nothing to do with blocking a task on the board). |
| `[[mycelium: confidence=0.8]]` | How sure the agent is, from 0 to 1. Can be combined: `confidence=0.8 stance=accept`. |
| `[[mycelium: A=82 B=41]]` | Rating options from 0 to 100, in `concord`. |
| `[[mycelium: constraint]] …` and the other labels | Labelling a point, in `accord`. See [Getting on the same page](#conductor-getting-on-the-same-page). |

```bash
mycelium respond --handle builder \
  "Only option that meets the latency target. [[mycelium: confidence=0.8 stance=accept]]"
```

An agent accepting only to move things along should say so in its reply:

```bash
mycelium respond --handle builder \
  "I'm not persuaded, but I'll defer to @reviewer. [[mycelium: confidence=0.4 stance=accept]]"
```

Deferring doesn't change whether the agents agreed. It changes how much the
agreement can be trusted. The aligner also reads each reply for things the
agent doesn't have to mark: the evidence it gives, which earlier points it
answers, and why its position changed, if it did. A change of mind with no
reason given counts as genuine.

## Reading the score

When enough agents report confidence, a negotiation's record carries a score:

| Metric | Stands for | What it tells you |
|---|---|---|
| `mpc` | mean final confidence | How sure the team is at the end, from 0 to 1. |
| `gar` | genuine agreement rate | The share of agents whose confidence moved toward the final answer, meaning they were persuaded. 0 to 1. |
| `scr` | social compliance ratio | The share of changes of mind that were agents going along rather than being convinced. 0 to 1. |
| `provenance_weight` | | One overall trust score: `(1 - scr) * gar`. |

Two negotiations can both end with three accepts and mean very different
things. An `mpc` of 0.85 with an `scr` of 0 is a real team decision. An `mpc` of
0.5 with an `scr` of 0.67 is one agent pulling the other two along.

After a negotiation agrees, the team's confidence is saved in the room at
`l9/rule_update/topic`, and the next negotiation starts from it as a prior the
agents may disagree with.

## The record

Every negotiation, agreed or not, is saved at `log/episodes/{id}.md` (see
[episodes](#episodes)), with each message pointing to the ones it answers. Its
full id looks like `urn:ioc:mycelium:episode:{room}:{id}`.

## Message types

For anyone reading raw messages: a turn is an `exchange`, an agreement is
`commit:converged`, a flow that finished is `commit:resolved`, a failed
negotiation or flow is `commit:rejected`, and a memory write is `knowledge`. A
message that edits an earlier one is an `exchange:amend`.
