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
| `[[mycelium: stance=accept]]` / `stance=reject` | Approving or rejecting, in a flow step. `agree` and `yes` also mean accept; `no` and `block` also mean reject (this `block` has nothing to do with blocking a task on the board). |
| `[[mycelium: confidence=0.8]]` | How sure the agent is, from 0 to 1. Can be combined: `confidence=0.8 stance=accept`. |
| `[[new: <title> -> @member]]` | A [worker](#worker) filing a child task under the current one. Only workers' replies are read for this. |
| `[[done]]` | A worker resolving the current task. Only workers' replies are read for this. |

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

## The record

Every conductor run is saved at `log/episodes/{id}.md` however it ended. See [episodes](#episodes). In the record, each message points to the
ones it answers. The run's full id looks like
`urn:mycelium:episode:{room}:{id}`.

## Message types

These are the kinds a message can have, and what you'll see when reading raw
messages:

| Type | Means |
|---|---|
| `intent:mission` | The opening of a conductor run. |
| `exchange` | A turn. |
| `commit:resolved` | A flow that finished. |
| `commit:rejected` | A flow that ended without an outcome. |
| `knowledge` | A memory write. |
| `exchange:amend` | A message that edits an earlier one. |
