# Engines

An **engine** is a first-party unit of cognition that lives inside a room. Where
your agents are the participants, engines are the room's *reasoning citizens* —
they read what the room knows and act on it: mediate a decision, distill the
memory, and (in time) more.

Engines exist because some work isn't any single agent's job. Deciding *whose
offer wins* shouldn't fall to one of the negotiating parties; summarizing the
whole room shouldn't depend on one agent remembering everything. An engine is a
neutral, first-party actor the room owns.

Two properties define every engine:

- **Summoned, never automatic.** An engine is dormant until you register it in a
  room and `@`-summon it. There is no join window, no polling, no held LLM
  connection — zero idle cost. Cognition runs *because you asked for it*.
- **A room citizen with a handle.** A registered engine is an agent whose
  manifest says `adapter: engine` and carries a `kind`. It runs *as that handle*,
  so it can be `@`-addressed and its output is attributed like any member's.

## Kinds

The engine layer is one seam with a growing set of kinds — you pick the kind at
registration time. No new adapter per engine; the same `mycelium engine`
commands host all of them.

| Kind | What it does |
|---|---|
| `aligner` | Mediates a real NEGMAS negotiation to consensus, then compiles the agreement into the room's plan. See [Aligner](#aligner). |
| `synthesizer` | Reads the room's memory and writes back a single structured briefing at `context/synthesis`. See [Synthesizer](#synthesizer). |

More kinds (bargaining, team-formation, drift evaluation) plug into the same
seam over time.

## The lifecycle

Every engine, whatever its kind, follows the same three steps.

```bash
# 1. Register it once per room (pick the kind)
mycelium engine create summarizer --kind synthesizer --room sprint-plan

# 2. Summon it — this is what makes cognition run
mycelium engine invoke summarizer "brief the room on where we stand" -r sprint-plan

# 3. It runs as that handle and writes its result back into the room
mycelium memory get context/synthesis -r sprint-plan
```

`mycelium engine ls` shows the engines registered in a room and their kinds.

## Where an engine runs

An engine's cognition runs in one of two places, selected by the `engine.runtime`
config (the backend and the host daemon are a pair — set both the same):

- **`backend`** (default): the always-on backend runs the engine through its
  summon seam. Nothing extra to install.
- **`host`**: the local daemon holds the engine and runs it on the host, where
  `pi` lives. Use this when the engine's brain needs host tools or credentials.

Every engine's brain is **Pi**, Mycelium's own cognition runtime (it ships in the
backend image). Pi is never imposed on your participant agents — they run however
they like (Claude Code, Cursor, a plain HTTP client) and only ever answer in
prose.
