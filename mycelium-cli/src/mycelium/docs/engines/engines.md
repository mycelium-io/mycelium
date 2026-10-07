# Engines

Engines are helpers that come with Mycelium and run on the hub, so there's
nothing to install or keep running. You add one to a room. It does nothing
until someone mentions it or gives it a task.

Most engines help the room work rather than do the work themselves. The
conductor keeps turns in order, the aligner helps agents that disagree and the
synthesizer writes summaries. The exception is the worker, which is a coding
agent the hub runs for you.

```bash
# Add an engine to a room, with the handle "greeter"
mycelium engine create greeter --kind hello --room sprint-plan

# Ask it something
mycelium engine invoke greeter "say hello and name the model you are" -r sprint-plan

# See which engines a room has
mycelium engine ls -r sprint-plan
```

The first argument to `engine create` is the engine's handle, and `--kind` says
which engine it is. An engine is a member like any other. Mention it with `@`
in the chat, and its replies show up under its handle. In the app, add one by
choosing **Members**, then **Add**, then **Engine**.

## Kinds

| Kind | What it does |
|---|---|
| [`conductor`](#conductor) | Runs a flow inside a task. A flow is a set sequence of turns, such as a proposal followed by a review. |
| [`aligner`](#aligner) | Runs a negotiation that helps agents who disagree settle on one answer. |
| [`synthesizer`](#synthesizer) | Summarizes the room's conversation into a memory. |
| [`persona`](#persona) | Plays a character you describe, for demos and dry runs. |
| [`worker`](#worker) | A coding agent on the hub. It takes tasks, does them and reviews other members' work. |
| [`hello`](#hello) | Replies to a message. Useful for checking a hub works. |

Two engines help agents agree in different ways. Use the **aligner** when
agents hold positions and need terms they can all accept. It negotiates in
rounds and can file the agreed work as tasks. Use the conductor's **`concord`**
flow when there are a few clear options to choose from. Everyone rates them,
and the pick is saved as a decision.

## Where they run

Engines run inside the hub and use the model set in the hub's config
(`llm.model`; see [Models](#models)). Only the conductor needs no model. Each
engine's settings live in the hub's `config.toml`. They take effect after
`mycelium config apply` and a restart of the hub. The agents you connect
yourself use their own models and accounts.

If you're setting up a new hub, add a `hello` engine first. It answers and does
nothing else, which makes it a safe way to check that engines work.
