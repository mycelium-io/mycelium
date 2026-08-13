# Synthesizer

The synthesizer is the distillation [engine](#engines): the `kind` that reads a
room's memory and writes back a single briefing everyone can pick up. The
[aligner](#aligner) converges a negotiation; the synthesizer summarizes what the
room already knows.

Like every engine, it is summoned. Nothing runs until you register it in a
[room](#rooms) and invoke it, so there is no polling and no held connection.

```bash
# Register the synthesizer once per room
mycelium engine create summarizer --kind synthesizer --room sprint-plan

# Summon it to compile a briefing
mycelium engine invoke summarizer "brief the room on where we stand" -r sprint-plan

# Read the result back
mycelium memory get context/synthesis -r sprint-plan
```

## How it distills

On summon, the synthesizer reads every [memory](#memory) namespace (decisions,
status, context, work, and the plan) and runs one **Pi** turn to compile them
into a single markdown briefing: the room's goal, key decisions, current status,
and open work. It upserts that briefing as a `knowledge` memory at
`context/synthesis`, so it is versioned, searchable, and shared like any other
memory.

Run it again after a burst of activity and the briefing upserts in place with
its version incremented, so the room always has one current summary instead of a
pile of stale ones.

## Faithfulness

The briefing reflects only what is in the room's memory; the synthesizer does
not invent facts. If its Pi turn fails, it writes nothing rather than a
half-formed summary.

The synthesizer holds no [episode](#episodes) and drives no negotiation. It
reads the room, summarizes it, and writes the result back. It shares the rest of
the engine model: the summon lifecycle and [where it runs](#engines) (the
backend or the host daemon), with every brain running a **Pi** turn.
