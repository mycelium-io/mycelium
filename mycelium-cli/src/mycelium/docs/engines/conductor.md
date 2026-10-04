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
| `review` | author, reviewer | The author does the work. The reviewer checks it and approves it or sends findings back, until it's approved. |
| `concord` | none | Help them agree. Everyone suggests an option and rates them all, and the pick is the option the least happy member likes best. See [Helping members agree](#conductor-helping-members-agree). |
| `accord` | lead | Get on the same page before work starts. Everyone says what the task is, what's out of scope and what done means; the lead writes one shared summary; it's locked once nobody objects. |

Members approve or reject by ending their reply with
`[[mycelium: stance=accept]]` or `[[mycelium: stance=reject]]`.

## Helping members agree

When members disagree about how to do a task, `concord` gets them to one
option they can all live with:

```bash
mycelium board coordinate decisions/double-charge-refunds conductor \
  "concord @builder @reviewer @julia: refund double charges automatically, or send them to support?"
```

1. **Suggest.** Everyone suggests one option. Each option gets a letter.
2. **Rate.** Everyone rates every option from 0 to 100 for their own role,
   all at the same time, so nobody sees the others' ratings first. A rating
   goes in the marker, one capital letter per option:
   `[[mycelium: A=82 B=41]]`.
3. **Pick.** The pick is the option the least happy member likes best, so
   nobody gets steamrolled. Code makes the pick, never a model.
4. **Fix, if needed.** If someone rated the pick below 70, that member
   suggests a fix, and everyone rates it.
5. **Stop.** It stops as soon as everyone rates the pick 70 or more, after
   two fixes, or when the only problem is someone who isn't answering.

After each rating round the thread shows a scorecard: the options, everyone's
ratings, and who is below the bar. It ends with one line, such as
"Everyone's on board: going with C" or "Couldn't get everyone there. Best was
B". When everyone agrees, any follow-up work from the decision is filed under
the task.

A reply without readable ratings is asked once more. A missing rating is
never guessed from what someone wrote: it counts against the option it's
missing from, so an option can't win just because the people who dislike it
didn't answer.

## Who can take part

Any member can fill a role: your own agent, a [persona](#persona), a
[worker](#worker), or you. To take a role yourself, put your own handle in the
message. When it's your turn, reply in the task's thread in the app. From a
terminal, you take your turn the same way an agent does:

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

![A gated flow at the top of a task's thread, waiting on the step that proposes](app-thread-flow.png)

Each run is also saved as a record under `log/episodes/`, with the flow, who
played each role, and every step taken.

## How a flow ends

A flow ends at one of its end steps, as either `resolved` or `rejected`. If it
reaches its step limit first, it ends as `rejected`. A `concord` run that
everyone agrees on ends as `converged`: the one ending that files follow-up
work, as sub-tasks of the task it ran in.

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
- `bottleneck`: the member the last pick left least happy (only after a pick)

`next` is either a step id, or a map that picks the next step from the answer:
`accept`, `reject`, `silent` (no answer in time) and `default`.

Other options:

- `rounds: 2` repeats an `each` or `all` step.
- `wait: none` asks without waiting for an answer.
- `max_steps` limits how many steps a run can take. A step counts once
  however many members it asks.
- `collect: options` makes each reply an option; `collect: scores` records
  each reply's ratings of the options.
- `require: stance` or `require: scores` asks a reply that's missing it once
  more. A stance still missing after that counts as a rejection, so a written
  objection is never read as agreement.

A pick is a step with `kind: select`. It asks nobody, takes a `threshold`
(0.7 means everyone rates it 70 or more) and `max_repairs`, and goes on by how
the pick went: `feasible` (everyone's on board), `infeasible` (someone can fix
it), `stuck` (a fix can't help) and `default`. An end step of
`end: converged` can only be reached from a pick's `feasible` edge. Print
`concord` with `show concord` to see one in full.

Prompts can use these placeholders:

| Placeholder | Filled with |
|---|---|
| `{ask}` | The question from the message that started the flow. |
| `{task}` | The task's key, such as `work/rotate-signing-key`. |
| `{title}` | The task's title, such as "Rotate the signing key". Reads better in a prompt than the key. |
| `{reply}` | The last answer. |
| `{replies}` | Every member's latest answer, one per line. |
| `{handles}` | The members taking part. |
| `{round}`, `{rounds}` | The current round and the total. |
| `{options}`, `{option_labels}` | Every option suggested so far, as `A. …` lines, and the marker to rate them all with, such as `A=.. B=..`. |
| `{new_options}`, `{new_labels}` | The options no one has rated yet, and the marker to rate them with, such as `C=..`. |
| `{pick}`, `{scores}` | The best option so far in full, and the last pick's scorecard. |
| `{shortfall}` | What the least happy member is short by, such as "You rated option B 38; the bar is 70". |

If a flow doesn't make sense, for example a step leads nowhere or there's no
end step, the conductor refuses to run it and says why. Each run keeps its own
copy of the flow, so editing the memory changes future runs, not past records.
