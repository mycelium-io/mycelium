# Hello

The hello engine is the [engine](#engines) that does nothing on purpose. Summon
it and it runs one **Pi** turn on whatever you said, posts the answer into the
room, and stops. No negotiation, no memory write, nothing compiled — the only trace it
leaves is the message it posts.

That is what makes it useful. The [aligner](#aligner) opens a negotiation
episode and the [synthesizer](#synthesizer) writes a memory back, so neither is
something you want to fire into a live room just to check the wiring. Hello is,
which makes it the first thing to try on a new hub.

```bash
# Register it once in the room
mycelium engine create hello --kind hello --room sprint-plan

# Summon it
mycelium engine invoke hello "say hello and name the model you are" -r sprint-plan
```

A reply in the room means the whole engine path works.

## What a reply proves

`mycelium doctor` already checks that the hub can reach a model — but that
probe stops at the completion. Every rung above it is untested until an engine
actually runs. A hello reply walks all of them:

- the manifest gate that routes an `@`-mention to a registered engine of the
  right `kind`, and to nothing else
- the engine runtime branch that decides who owns the run
- the guard that stops an engine firing on its own message
- a one-shot Pi turn against the configured `llm.model` / key / base URL
- the channel send, and the persister writing the message into the transcript

If no reply appears, the failure is in exactly one of those, and the backend
logs say which.

## Fail-loud

A probe that fails silently is worse than no probe, so hello never goes quiet:
if its Pi turn times out or errors, it posts the reason into the room instead of
an answer. Silence means the summon never reached it — a different failure, and
a more useful thing to know.

## Holding nothing

Hello keeps no state between summons and answers each one from scratch, so it is
not a chat partner — it is a probe with a personality. Ask it something twice
and it will not remember the first time. For cognition that carries context,
that is what the aligner and the synthesizer are for.
