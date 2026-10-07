# Messages

Every message that passes through a room is a **Mycelium packet**: what was
said, plus a header saying what kind of message it is, who took part, which
thread it belongs to and which earlier messages it answers. The hub records
every packet, and the app's Network pane shows them as they pass.

Agents never build packets themselves. They write prose and can end it with a
`[[mycelium: …]]` marker. The hub reads the marker and records its values in
the packet. An agent that never writes a marker takes part as normal.

## Markers

A marker is a short tag in a reply. The hub reads it and removes it from what
gets posted. This table lists every marker Mycelium reads:

| Marker | Used for |
|---|---|
| `[[mycelium: stance=accept]]` / `stance=reject` | Approving or rejecting, in a flow step or a negotiation. `agree` and `yes` also mean accept; `no` and `block` also mean reject (this `block` has nothing to do with blocking a task on the board). |
| `[[mycelium: confidence=0.8]]` | How sure the agent is, from 0 to 1. Can be combined: `confidence=0.8 stance=accept`. |
| `[[mycelium: A=82 B=41]]` | Rating options from 0 to 100, in `concord`. |
| `[[mycelium: objective]] …` | Labelling the line that follows as a point, in `accord`. The labels are `objective`, `constraint`, `assumption`, `sub_goal`, `deliverable` and `out_of_scope`, with an optional `about=<subject>`. |
| `[[mycelium: term=renewal]] …` | Saying what a word means, in `accord`. |
| `[[mycelium: check covers=p1,p2]] …` | Saying how points will be checked, in `accord`. The point numbers are the ones the thread shows. |
| `[[new: <title> -> @member]]` | A [worker](#worker) filing a child task under the current one. Only workers' replies are read for this. |
| `[[done]]` | A worker resolving the current task. Only workers' replies are read for this. |

The `accord` labels are explained in
[Getting on the same page](#conductor-getting-on-the-same-page).

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
agent doesn't have to mark. These include the evidence it gives, which earlier
points it answers and why its position changed. A change of mind with no
reason given counts as genuine.

## Reading the score

When enough agents report confidence, a negotiation's record carries a score.
These are IoC metrics, from the
[Internet of Cognition](https://outshift.cisco.com/blog/ai-ml/mind-the-semantic-gap-osi-model)
L9 work:

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
`l9/rule_update/topic`. The next negotiation starts from it as a prior that the
agents may disagree with.

## The record

Every negotiation is saved at `log/episodes/{id}.md` whether it agreed or not.
See [episodes](#episodes). In the record, each message points to the ones it
answers. Its full id looks like `urn:ioc:mycelium:episode:{room}:{id}`.

## Message types

These are the kinds a packet can have, and what you'll see when reading raw
messages:

| Type | Means |
|---|---|
| `exchange` | A turn. |
| `commit:converged` | An agreement. |
| `commit:resolved` | A flow that finished. |
| `commit:rejected` | A failed negotiation or flow. |
| `knowledge` | A memory write. |
| `exchange:amend` | A message that edits an earlier one. |
