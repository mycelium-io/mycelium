# Synthesizer

The synthesizer is the distillation [engine](#engines): the `kind` that reads a
room's **conversation** and writes what it learned into **memory**. The
[aligner](#aligner) converges a negotiation; the synthesizer moves what the room
said into what the room keeps.

That direction is the whole point. Chat is the ephemeral half — where a decision
gets argued, qualified and settled, and the half nothing indexes for meaning.
Memory is the durable half. The synthesizer is the bridge between them.

Like every engine, it is summoned. Nothing runs until you register it in a
[room](#rooms) and invoke it, so there is no polling and no held connection.

```bash
# Register the synthesizer once per room
mycelium engine create summarizer --kind synthesizer --room sprint-plan

# Summon it to distill what has been said since last time
mycelium engine invoke summarizer "brief the room on where we stand" -r sprint-plan

# Re-distill the whole transcript instead of just the new tail
mycelium engine invoke summarizer "--all" -r sprint-plan

# Read the result back
mycelium memory get context/synthesis -r sprint-plan
```

## How it distills

On summon, the synthesizer reads the room's chat and runs one **Pi** turn to
distill it into a single markdown briefing: what was decided, what changed, what
is in flight, and what is still open. It upserts that briefing as a `knowledge`
[memory](#memory) at `context/synthesis`, so it is versioned, searchable, linked
and shared like any other memory.

It reads the transcript **by message type**, so only real chat reaches the
prompt. The room's feed also carries L9 frames and coordination messages whose
content is a serialized envelope; those are excluded structurally, and a
briefing never comes back with JSON quoted inside it.

## Incremental by default

Each run covers only what has been said since the last one. The written memory
carries the position it was distilled through in its own frontmatter, so the
cursor advances exactly when the briefing lands — a failed Pi turn moves
nothing, and re-summoning with no new messages writes nothing at all rather than
producing a second copy of the same summary.

The standing briefing is carried into the next run as context, so a new slice is
folded into what is already known rather than replacing it. Pass `--all` in the
summon text to re-read the whole transcript from the start.

The synthesizer also speaks its briefing into the room, which means its own
words are in its next input. Messages from any registered synthesizer handle are
dropped from the corpus before the prompt is built, so it never feeds on itself.

## Faithfulness

The briefing reflects only what was actually said; the synthesizer does not
invent facts. If its Pi turn fails, it writes nothing rather than a half-formed
summary.

The synthesizer holds no [episode](#episodes) and drives no negotiation. It
reads the room, distills it, and writes the result back. It shares the rest of
the engine model: the summon lifecycle and [where it runs](#engines)
(backend-side), with every brain running a **Pi** turn.

## Summarizing memory instead

Summarizing the memory store — a briefing over what is already durable — is a
different feature, not the default one. Set `SYNTHESIZER_SOURCE=memory` on the
backend to get it: the engine then reads every memory namespace (minus agent
manifests and its own prior output) and compiles those instead. That path is not
incremental; there is no transcript position to hold.
