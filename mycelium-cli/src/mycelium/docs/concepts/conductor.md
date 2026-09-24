# Conductor

The conductor runs a set sequence of turns inside a task, called a flow. For
example: one member proposes something, another approves or rejects it, and
a rejection sends it back for another try. The conductor makes sure each
member speaks when it's their turn, and only then.

It doesn't use a model. The members do all the thinking; the conductor only
decides who goes next, based on the flow and on how the last member answered.

```bash
mycelium engine create conductor --kind conductor --room sprint-plan

mycelium board coordinate work/rotate-signing-key conductor \
  "gated @api @sec: rotate the signing key without downtime"
```

The message starts with the flow's name, then the members in the order of the
flow's roles, then the question. Here `api` is the proposer and `sec` is the
reviewer.

A flow always runs on a task, and everything happens in that task's thread.
To see the flows a room can run, use
`mycelium engine invoke conductor "list"`.

## Built-in flows

| Flow | Roles | What happens |
|---|---|---|
| `gated` | proposer, guardian | The proposer says what it plans to do. The guardian approves or rejects it. A rejection goes back to the proposer with the reason, until the guardian approves or the step limit is reached. |
| `fan-out` | lead | Every other member is asked the question at once. The lead gets all the answers and combines them into one. |
| `round-robin` | none | Members speak one after another, each seeing what the others said, for two rounds. |
| `swarm` | lead | Each member says which part of the task it would take. Then the lead splits the task into one child task per member. [`mycelium swarm`](#swarm) starts with this. |

Members approve or reject by ending their reply with
`[[mycelium: stance=accept]]` or `[[mycelium: stance=reject]]`.

## Who can take part

Any member can fill a role: your own agent, a [persona](#persona), a
[worker](#worker), or you. To take a role yourself, put your own handle in the
message. When it's your turn, reply in the task's thread in the app, or from
the terminal:

```bash
mycelium board coordinate work/rotate-signing-key conductor "gated @api @julia: rotate the key"

mycelium await --handle julia
mycelium respond --handle julia "Not without a canary. [[mycelium: stance=reject]]"
```

## Taking turns

While a flow is running, only the member whose turn it is can post in the
task's thread. Anyone else who tries gets an error saying whose turn it is,
and their message isn't posted. The rest of the room isn't affected: the room
chat and other tasks' threads stay open to everyone. The members list shows
who has the turn.

## Following along

In the task's thread, each question from the conductor shows as one line,
such as `review → sec · turn 2 of 6`. Click it to see the full prompt.

In the app, the flow is drawn at the top of the thread, with the current step
highlighted and the path taken so far. When the flow finishes, it shows how it
ended and each step that was taken. If a task has run more than one flow, you
can open the earlier ones from there.

Each run is also saved as a record under `log/episodes/`, with the flow, who
played each role, and every step taken.

## How a flow ends

A flow ends at one of its end steps, as either `resolved` or `rejected`. If it
reaches its step limit first, it ends as `rejected`.

Finishing a flow doesn't finish the task. To mark the task done, resolve it as
usual with `mycelium board resolve`.

## Writing your own flow

A flow is a memory under `protocols/`, written in YAML. Saving one as
`protocols/gated` replaces the built-in `gated` in that room, and a new name
adds a new flow.

To start from a built-in, print it and edit it:

```bash
mycelium engine invoke conductor "show gated"
```

For example:

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
    prompt: "On the table:\n\n{reply}\n\nApprove or reject, ending with a stance marker."
    next: {accept: done, reject: draft, default: draft}
  - id: done
    end: resolved
```

Each step has an `id`, and either asks someone (`to`) and says where to go
next (`next`), or ends the flow (`end: resolved` or `end: rejected`).

`to` can be:

- a role, such as `author`
- `each`: every member, one at a time
- `all`: every member at once
- `workers`: every member that doesn't have a role

`next` is either a step id, or a map that picks the next step from the answer:
`accept`, `reject`, `silent` (no answer in time) and `default`.

Other options:

- `rounds: 2` repeats an `each` or `all` step.
- `wait: none` asks without waiting for an answer.
- `max_steps` limits how many steps a run can take.

Prompts can use these placeholders:

| Placeholder | Filled with |
|---|---|
| `{ask}` | The question from the message that started the flow. |
| `{task}` | The task's key, such as `work/rotate-signing-key`. |
| `{reply}` | The last answer. |
| `{replies}` | Every member's latest answer, one per line. |
| `{handles}` | The members taking part. |
| `{round}`, `{rounds}` | The current round and the total. |

If a flow doesn't make sense, for example a step leads nowhere or there's no
end step, the conductor refuses to run it and says why. Each run keeps its own
copy of the flow, so editing the memory changes future runs, not past records.
