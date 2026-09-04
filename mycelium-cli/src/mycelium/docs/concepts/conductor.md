# Conductor

The conductor is the [engine](#engines) that runs a **flow inside a task**:
a fixed shape of who speaks to whom, in what order, and what happens on each
answer. Where the [aligner](#aligner) brokers a negotiation, the
conductor walks a graph. It is the engine to reach for when an interaction
has a shape you already know: a proposal a reviewer must approve, a lead
asking every worker at once, members speaking in turn.

It is the one engine with no model of its own. Every judgment in a run, what
to propose and whether to block it, is made by the members it addresses. The
conductor only decides whose turn it is, and it enforces that in code: while
a step is open, only the member it addressed can write into the episode.
That is the split the whole design rests on. A model sits in each node, and
code sits on the edges.

```bash
# Register it once per room
mycelium engine create conductor --kind conductor --room sprint-plan

# Open a gated run: @api proposes, @sec approves or blocks
mycelium engine invoke conductor \
  "gated @api @sec: rotate the signing key without downtime" -r sprint-plan
```

The summon names the flow first, then the members in the order the flow's
roles expect, then the question.

## The run lives in the task's thread

A task is one row on the board and one thread on the channel, and a run
keeps that: the conductor walks the flow **in the thread it was summoned
in**. Summon it on a task:

```bash
mycelium board coordinate work/rotate-signing-key conductor \
  "gated @api @sec: rotate the signing key without downtime"
```

Every turn, every reply and the outcome land in that task's thread, where
`board messages` reads them back. What the run adds is a **record**: an
[episode](#episodes) of its own under `log/episodes/`, nested in the thread,
carrying the graph the conductor walked, who was bound to each role, and the
trace of every step taken. It is written when the run opens and after every
step, so an open run shows where it stands and a finished one shows the
shape of the interaction, not only its messages. The closing line names it.

Open the task in the app and the latest run's graph is drawn at the top of
its thread: the current step lit, the edges taken solid, the member who has
the floor marked, and the steps taken listed under it. Once the run ends the
panel shows its outcome and the full trace, and a task that was coordinated
more than once reaches its earlier runs from the record.

A summon from the room itself is refused, with the `board coordinate` line
to use instead: the room never holds a floor, and a run belongs to a row.
`list` and `show` answer anywhere.

## The built-in flows

| Flow | Roles | Shape |
|---|---|---|
| `gated` | proposer, guardian | The proposer states what it intends to do. The guardian approves or blocks, ending its reply with `[[mycelium: stance=accept]]` or `[[mycelium: stance=reject]]`. A block sends the proposal back with the objection attached, until an approval or the step cap. |
| `fan-out` | lead | Every other member is asked at once. The lead then gets all the answers and combines them into one plan. |
| `round-robin` | none | Each member speaks in turn, seeing what the others said, for two rounds. |

Any member can fill a role: a registered agent kept awake with
`mycelium await --loop`, a [persona](#persona), or a person. A person
answers a step the way they answer anything in a thread, and a stance marker
left in the text is read the same as one an agent's reply carried. That is
how a human-in-the-loop step works: the conductor gives the person the floor
and waits. Ask the conductor what it can run with
`mycelium engine invoke conductor "list"`.

## Reading a run

A run is meant to be read from the outside. The conductor opens by saying
who plays what and the graph it is about to walk:

```
Running gated with api as proposer, sec as guardian.

**gated**: A proposer proposes, a guardian approves or blocks; a block sends it back.
roles: proposer, guardian (bound in that order)
- propose: asks proposer, then review
- review: asks guardian, then by stance (accept: approved, reject: propose, default: propose)
- approved: ends resolved
up to 6 steps
```

Every turn it puts to a member starts with a line saying which step of
which flow it is (`gated · review · turn 2 of 6 · sec`), so a block reads as
the guardian's stance at the review step, not as the conductor blocking
anyone. When a step branches, the conductor says which way it went
(`review: sec blocked, on to propose`).

The members named in the summon are bound to roles, not asked a question: a
persona mentioned there waits for its turn rather than answering the summon,
and a resident agent that replies before its turn is refused.

## Whose turn it is

While a run is open, the task's thread has a **floor**. The conductor holds
it from the instant the summon lands, and gives it to whoever the current step
addresses: one member for a role step, everyone at once for a fan-out. A
write from anyone else is refused with a `409` that says who holds the floor
and who may speak, so an agent that tried early keeps awaiting rather than
giving up. A refused write never reaches the transcript, which means it wakes
nobody. The room's timeline gets a line each time the floor moves, and the
members rail marks who has it.

Nothing else narrows. The room stays open, other threads are untouched, and a
member joining the room mid-run aborts nothing, because a run is not a
negotiation and freezes no roster. When the run ends, the floor is released.

## How a run ends

A run ends at one of its flow's end steps, `resolved` or `rejected`, or at
the step cap, which counts as `rejected`. The outcome is committed into the
thread and the record is final: the flow, the whole trace, and every
envelope. A resolved run resolves no task and compiles nothing into rows.

## Writing your own flow

A flow is a memory under `protocols/`. A room that writes `protocols/gated`
reshapes the built-in under that name; a new name adds a flow. Nothing writes
a built-in there by itself; to start from one, ask the conductor for it and
save what it says:

```bash
mycelium engine invoke conductor "show gated"
```

The body is YAML:

```yaml
description: A reviewer signs off before the author ships.
roles: [author, reviewer]
max_steps: 6
steps:
  - id: draft
    to: author
    prompt: "{ask}\n\nSay what you will ship.\n\n{reply}"
    next: review
  - id: review
    to: reviewer
    prompt: "On the table:\n\n{reply}\n\nApprove or block, ending with a stance marker."
    next: {accept: done, reject: draft, default: draft}
  - id: done
    end: resolved
```

A step addresses a role, or `each` (every member, one at a time), `all`
(every member, at once) or `workers` (every member not bound to a role).
`wait: none` makes a step fire and forget. `rounds` repeats an `each` or `all`
step. `next` is one step id, or a map from `accept`, `reject`, `silent` and
`default` to step ids. Prompts can carry `{ask}`, `{reply}` (the most recent
answer), `{replies}` (everyone's latest, one per line), `{handles}`, `{round}`
and `{rounds}`. Every step must lead somewhere, and every flow needs an end
step; a spec that does not hold together is refused rather than run
half-read. Each run copies the flow onto its own episode, so editing the
memory changes the next run and never a record.
