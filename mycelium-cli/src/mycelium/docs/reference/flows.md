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

If a flow doesn't make sense, the conductor refuses to run it and says why. For
example, a step might lead nowhere or there might be no end step. Each run
keeps its own copy of the flow. Editing the memory changes future runs but not
past records.

## Steps

Each step has an `id`. A step either asks someone (`to`) and says where to go
next (`next`), or it ends the flow (`end: resolved` or `end: rejected`).

`to` can be:

- a role, such as `author`
- `each`: every member taking part, one at a time
- `all`: every member taking part, at once
- `workers`: every member taking part that isn't bound to a role, at once
- `bottleneck`: the member the last pick left least happy (only after a pick)
- `contested`: everyone who means something different by a word (only after a
  check of the words)

`next` is either a step id or a map that picks the next step from the answer.
The map's keys are `accept`, `reject`, `silent` (no answer in time) and
`default`.

Other options:

- `rounds: 2` repeats an `each` or `all` step.
- `wait: none` asks without waiting for an answer.
- `max_steps` limits how many steps a run can take. A step counts once however
  many members it asks. The thread's "turn 2 of 6" counts the same steps.
- `collect: options` makes each reply an option, with a `why:` line as its
  reason. `collect: scores` records each reply's ratings (`A: 80 - why`) and
  asks once more for any that came without a reason. `collect: anchors`
  records each member's ratings of the two reference outcomes (`bad: 10 - why`,
  `ideal: 90 - why`). `collect: keywords` records the key terms members name
  (`term: …`). `collect: pieces` merges each reply's labelled points, terms and
  checks into the shared summary being built.
- `require: stance`, `require: scores` or `require: pieces` asks once more for a
  reply that's missing it. A stance still missing after that counts as a
  rejection. A reply that still has no labels is kept as written.

## Steps that ask nobody

A **pick** is a step with `kind: select`. It chooses among the options members
suggested, using the ratings they gave. Each rating is placed between that
member's ratings of the two reference outcomes, when the flow collected them.
It takes a `threshold` and `max_repairs`. A threshold of 0.6 means the pick
passes only if it's at least 60% of the way from each member's bad outcome to
their ideal. The message that starts a run can set them with `bar=70` and
`fixes=3`. Its `next` map picks the next step by how the pick went:

- `feasible`: everyone rated the pick and it meets the threshold for each.
- `infeasible`: someone is short of the threshold. The least happy can be asked
  for a fix (`to: bottleneck`).
- `stuck`: a fix can't help. Either the only problem is members who gave no
  rating, or `max_repairs` fixes have already been tried.
- `nothing`: there are no options to pick from.
- `default`.

A step with `end: converged` is only allowed right after a pick, as its
`feasible` next step. `show concord` prints one in full.

`accord` is built from two more kinds of step. `show accord` prints it.

- `kind: tally` looks at what's been gathered so far. With `of: points`, its
  `next` map uses `grew` when the last round added a point, `settled` when it
  added none, and `empty` when nobody has given any. With `of: terms`, it uses
  `contested` when two people mean different things by a word, and `clear`
  otherwise. `max_rounds` is how many times it can run before it moves on.
- `kind: lock` puts the shared summary together and saves it to the room's
  memory. Its `next` map uses `locked`, or `empty` when there's nothing to
  save.

To have everyone approve the summary before it's saved, save your own
`protocols/accord` with an ask step before the lock that requires a stance.

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
| `{options}`, `{rating_lines}` | Every option so far, as `A. …` lines with why each was proposed, and the lines to rate them with, each naming its option, such as `A (Ship on Friday): <0-100> - <why>`. |
| `{new_options}`, `{new_rating_lines}` | The options no one has rated yet, and the lines to rate them with. |
| `{pick}`, `{scores}` | The best option so far, and the last pick's scorecard. |
| `{standing}`, `{objections}` | How each member sees the best option so far, in words, and the reasons of those short of the bar. |
| `{shortfall}` | Where the least happy member stands, such as "For you, B is short of the bar, because the window is too short". |
| `{bad}`, `{ideal}`, `{bar_said}` | The two reference outcomes, and the bar said in terms of them. |
| `{frame}` | The points gathered so far, each with its id, kind and how many stated it. |
| `{key_terms}`, `{term_lines}` | The run's key terms, and the lines to define them with. |
| `{terms}` | The terms members defined, with any used in different senses side by side. |
| `{checks}` | The checks members gave, with the points each covers. |
| `{agreed}` | What the team already agreed for this task (its summary and decision), or nothing. |
