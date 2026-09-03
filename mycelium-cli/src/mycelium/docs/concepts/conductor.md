# Conductor

The conductor is the [engine](#engines) that runs a **protocol** inside a
task: a fixed shape of who speaks to whom, in what order, and what happens on
each answer. Where the [aligner](#aligner) brokers a negotiation, the
conductor walks a graph. It is the engine to reach for when a piece of work
has a shape you already know: a proposal that a reviewer must approve, a lead
asking every worker at once, a round where each member speaks in turn.

It is the one engine with no model of its own. Every judgment in a run, what
to propose and whether to block it, is made by the members it addresses. The
conductor only decides whose turn it is, and it enforces that in code: while a
step is open, only the member it addressed can write into the thread. That is
the split the whole design rests on. A model sits in each node, and code sits
on the edges.

```bash
# Register it once per room
mycelium engine create conductor --kind conductor --room sprint-plan

# Run the gated protocol inside a task: @api proposes, @sec approves or blocks
mycelium board coordinate work/rotate-signing-key conductor \
  "gated @api @sec: rotate the signing key without downtime"
```

The summon names the protocol first, then the members in the order the
protocol's roles expect, then the question. The run happens in the thread the
summon was made in, so the row's conversation carries the whole thing and
`board messages` reads it back. A summon from the room itself
(`engine invoke`) opens a thread of its own, because the room is never
narrowed to one speaker.

## The built-in protocols

| Protocol | Roles | Shape |
|---|---|---|
| `gated` | proposer, guardian | The proposer states what it intends to do. The guardian approves or blocks, ending its reply with `[[mycelium: stance=accept]]` or `[[mycelium: stance=reject]]`. A block sends the proposal back with the objection attached, until an approval or the step cap. |
| `fan-out` | lead | Every other member is asked at once. The lead then gets all the answers and combines them into one plan. |
| `round-robin` | none | Each member speaks in turn, seeing what the others said, for two rounds. |

Any member can fill a role: a registered agent kept awake with
`mycelium await --loop`, an engine such as [hello](#hello), or a person. A
person answers a step the way they answer anything in a thread, with
`board send`, and a stance marker left in the text is read the same as one an
agent's reply carried. That is how a human-in-the-loop step works: the
conductor gives the person the floor and waits.

## Whose turn it is

While a run is open, the thread has a **floor**. The conductor holds it, and
gives it to whoever the current step addresses: one member for a role step,
everyone at once for a fan-out. A write from anyone else is refused with a
`409` that says who holds the floor and who may speak, so an agent that tried
early keeps awaiting rather than giving up. A refused write never reaches the
transcript, which means it wakes nobody.

Nothing else narrows. The room stays open throughout, other threads are
untouched, and a member joining the room mid-run aborts nothing, because a
protocol run is not a negotiation and freezes no roster. When the run ends,
the floor is released and the thread takes anyone again.

## How a run ends

A run ends at one of the protocol's end steps, `resolved` or `rejected`, or at
the step cap, which counts as `rejected`. The outcome is committed onto the
thread and recorded at `log/episodes/{id}.md` like any coordination phase:
who took part, each step's prompt and reply, and how it ended. A resolved run
does not resolve the task it ran in, and does not compile anything into new
rows. It is a phase inside the task, and `board resolve` still finishes the
task.

## Writing your own

A protocol is a memory under `protocols/`, promoted the way a skill is. A room
that writes `protocols/gated` reshapes the built-in under that name; a new
name adds a protocol. The body is YAML:

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
and `{rounds}`. Every step must lead somewhere, and every protocol needs an
end step; a spec that does not hold together is refused rather than run
half-read.
