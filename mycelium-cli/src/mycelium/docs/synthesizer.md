# Synthesizer

The synthesizer is the distillation [engine](#engines) — the `kind` that reads a
room's memory and writes back a single briefing everyone can pick up. Where the
[aligner](#aligner) *converges* a negotiation, the synthesizer *distills* what
the room already knows.

Like every engine, it is *summoned*: nothing runs until you register it in a
[room](#rooms) and invoke it. There is no polling and no held connection.

```bash
# Register the synthesizer once per room
mycelium engine create summarizer --kind synthesizer --room sprint-plan

# Summon it to compile a briefing
mycelium engine invoke summarizer "brief the room on where we stand" -r sprint-plan

# Read the result back
mycelium memory get context/synthesis -r sprint-plan
```

## How it distills

On summon the synthesizer reads every [memory](#memory) namespace — decisions,
status, context, work, and the plan — and runs one **Pi** turn to compile them
into a single markdown briefing: the room's goal, key decisions, current status,
and open work. It upserts that briefing as a `knowledge` memory at
`context/synthesis`, so it is versioned, searchable, and shared like any other
memory.

Run it again after a burst of activity and the briefing upserts in place (its
version increments) — the room always has one current summary, never a pile of
stale ones.

## Faithful, never invented

The synthesizer is deliberately faithful: the briefing reflects only what's in
the room's memory, and it never invents facts. If its Pi turn fails it writes
nothing rather than a half-formed summary — a missing briefing is honest, a
fabricated one isn't.

Unlike the aligner it holds no [episode](#episodes) and drives no negotiation —
it is a pure read → summarize → write consumer. It shares the rest of the engine
model: the summon lifecycle and [where it runs](#engines) (the backend or the
host daemon), every brain a **Pi** turn.
