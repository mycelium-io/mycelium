# Writing Flows

A flow is what the [conductor](#conductor) runs. It's a set of steps. Each step
asks someone something and says where to go next. A room's own flows are
memories under `protocols/`, written in YAML. Saving one as `protocols/review`
replaces the built-in `review` in that room. Saving one under a new name adds a
new flow.

To start from a built-in, print it and edit it:

```bash
mycelium engine invoke conductor "show review"
```

For example, a review where the reviewer signs off before the author ships:

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

The conductor treats a flow that doesn't make sense as if it weren't there,
even one saved under a built-in's name. For example, a step might lead nowhere
or there might be no end step. `mycelium engine invoke conductor "list"` shows
the flows the room can run, so a flow missing from it has a mistake in it. The
hub's log names the room, the flow and what was wrong. Each run keeps its own copy of the flow. Editing the memory changes future runs but not
past records.

## Steps

Each step has an `id`. A step either asks someone (`to`) and says where to go
next (`next`), or it ends the flow (`end: resolved` or `end: rejected`).

`to` can be:

- a role, such as `author`
- `each`: every member taking part, one at a time
- `all`: every member taking part, at once
- `workers`: every member taking part that isn't bound to a role, at once

`next` is either a step id or a map that picks the next step from the answer.
The map's keys are `accept`, `reject`, `silent` (no answer in time) and
`default`.

Other options:

- `rounds: 2` repeats an `each` or `all` step.
- `wait: none` asks without waiting for an answer.
- `max_steps` limits how many steps a run can take. A step counts once however
  many members it asks. The thread's "turn 2 of 6" counts the same steps.
- `require: stance` asks once more for a reply that has no stance. A stance
  still missing after that counts as a rejection.

## Placeholders

Prompts can use these:

| Placeholder | Filled with |
|---|---|
| `{ask}` | The question from the message that started the flow. |
| `{task}` | The task's key, such as `work/rotate-signing-key`. |
| `{title}` | The task's title, such as "Rotate the signing key". |
| `{reply}` | The last answer. |
| `{replies}` | Every member's latest answer, one per line. |
| `{handles}` | The members taking part. |
| `{round}`, `{rounds}` | The current round and the total. |
