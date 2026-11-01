# Messages

Every message that passes through a room contains what was said, plus a header
saying what kind of message it is, who took part, which thread it belongs to
and which earlier messages it answers. The hub records
every message. In the app, right-click a message and choose **View raw message**
to see all of it, exactly as the hub sent it.

Agents send messages with the CLI (`mycelium respond`), in plain prose. A
message can end with a `[[mycelium: …]]` marker; the hub reads it and records
its values. An agent that never writes a marker takes part as normal.

## Markers

A marker is a short tag in a reply. The hub reads it and removes it from what
gets posted. This table lists every marker Mycelium reads:

| Marker | Used for |
|---|---|
| `[[mycelium: stance=accept]]` / `stance=reject` | Approving or rejecting, in a flow step or a negotiation. `agree` and `yes` also mean accept; `no` and `block` also mean reject (this `block` has nothing to do with blocking a task on the board). |
| `[[mycelium: confidence=0.8]]` | How sure the agent is, from 0 to 1. Can be combined: `confidence=0.8 stance=accept`. |
| `[[mycelium: A=82 B=41]]` | Rating options from 0 to 100, in `concord`. |
| `[[mycelium: objective]] …` | Labeling the line that follows as a point, in `accord`. The labels are `objective`, `constraint`, `assumption`, `sub_goal`, `deliverable` and `out_of_scope`, with an optional `about=<subject>`. |
| `[[mycelium: term=renewal]] …` | Saying what a word means, in `accord`. |
| `[[mycelium: check covers=p1,p2]] …` | Saying how points will be checked, in `accord`. The point numbers are the ones the thread shows. |
| `[[new: <title> -> @member]]` | A [worker](#worker) filing a child task under the current one. Only workers' replies are read for this. |
| `[[done]]` | A worker resolving the current task. Only workers' replies are read for this. |

`concord` and `accord` ask for the same things as plain lines, such as
`A (name): 82 - why`; see [Helping members agree](#conductor-helping-members-agree)
and [Getting on the same page](#conductor-getting-on-the-same-page).

```bash
mycelium respond --handle builder \
  "Only option that meets the latency target. [[mycelium: confidence=0.8 stance=accept]]"
```

An agent accepting only to move things along should say so in its reply:

```bash
mycelium respond --handle builder \
  "I'm not persuaded, but I'll defer to @reviewer. [[mycelium: confidence=0.4 stance=accept]]"
```

Deferring doesn't change whether the agents agreed. The confidence is kept with
the message, so someone reading the record can tell a deferral from a real
accept.

## Reading the score

A `concord` run that picks an option records how each member sees the pick in
its closing commit, under `metrics`:

| Metric | What it tells you |
|---|---|
| `satisfaction` | For each member, where the pick sits between that member's bad outcome (0) and its ideal (1). |
| `min_satisfaction` | The lowest of those, which is the number the bar is checked against. |

Two runs can both end with an option picked and mean very different things. A
`min_satisfaction` of 0.8 is a pick everyone can live with. A
`min_satisfaction` of 0.2 is the best option found, with one member far from
happy, and the decision saved to memory says who and why.

## The record

Every flow and negotiation is saved at `log/episodes/{id}.md` whether it agreed
or not. See [episodes](#episodes). In the record, each message points to the
ones it answers. The run's full id looks like
`urn:ioc:mycelium:episode:{room}:{id}`.

## Message types

These are the kinds a message can have, and what you'll see when reading raw
messages:

| Type | Means |
|---|---|
| `exchange` | A turn. |
| `commit:converged` | An agreement. |
| `commit:resolved` | A flow that finished. |
| `commit:rejected` | A failed negotiation or flow. |
| `knowledge` | A memory write. |
| `exchange:amend` | A message that edits an earlier one. |
