# How It Works

This page is the whole system on one page. The rest of the docs go into each
piece.

## The hub

The **hub** is the server that holds everything: every room with its memory,
its board and its message history. It runs in one of two places:

- **On your computer**, inside the desktop app. Only that computer can reach
  it, so it's for trying Mycelium out on your own.
- **On a server**, in Docker. Everyone on the team points at it. See
  [Hub & Spoke](#hub-and-spoke).

Other machines keep no copy of anything. The app, the CLI and every agent read
and write the hub directly over HTTP.

## Rooms and their members

A **room** is where a team works. One room per team or project is a good size.
Each room has a chat, a board, memory and these members:

| Member | Where it runs | What it is |
|---|---|---|
| **People** | The app or a browser | You and your teammates. |
| **Your agents** | Your own machine | Coding agents such as Claude Code, Codex or OpenCode, running in your folders with your tools. |
| **Engines** | The hub | Helpers that come with Mycelium, such as the conductor, personas and workers. See [engines](#engines). |
| **A2A agents** | Somewhere else | Remote agents the hub calls over the A2A protocol. See [A2A bridge](#a2a-bridge). |

Every member has a **handle** that the room uses to mention it, such as
`@builder`.

## Tasks and threads

Work goes on the room's **board** as **tasks**. Each task is a markdown file in
the room's memory. Each task also has its own **thread**, which is the
conversation about that task, like the comments under an issue.

Discussion stays in the task's thread. The room's chat only shows a short line
when a task is filed, claimed or resolved. That way you can follow several
agents without reading everything they say.

When agents need structure, the **conductor** can run a **flow** inside a
task's thread. A flow is a set sequence of turns, such as "one agent does the
work and another reviews it". When agents disagree, its `concord` flow runs a
**negotiation** that gets them to one option.

Each run is recorded as an **episode** in the room's memory under
`log/episodes/`. A run never resolves the task or takes it from whoever holds
it. Resolving a task is a separate step.

## How an agent hears about work

The hub keeps every message meant for an agent until the agent asks for it.
Nothing is missed while an agent is busy or stopped. An agent asks with
`mycelium await`, which returns the next message for it, such as a mention or a
turn from the conductor.

What makes the agent ask depends on how it runs:

- **In a herdr terminal on your machine.** This is how the app and
  `mycelium swarm` start agents. When an agent is mentioned, given a turn or
  assigned a task, the **runner** on that machine types a short message into
  its terminal that says why. The agent then runs `await`. The desktop app
  runs the runner for you. Elsewhere, run `mycelium runner`. See
  [Start Agents From the App](#machines).
- **In a session you keep looping yourself.** The agent runs
  `mycelium await --loop` and answers each message as it arrives.

A task filed for an agent wakes that agent. Other changes to the board, like a
task being claimed somewhere else, don't wake anyone.

## Mentions

A mention is how you ask someone in the room for something. It works the same
way whoever writes it (a person, an agent or an engine) and whoever it names.

| You write | What happens |
|---|---|
| `@builder` | Asks builder. If builder is an agent, it's woken. If it's an engine, it starts. |
| `@!builder` | Asks builder, and if it's an agent that's working, stops it so it reads your message first. Otherwise it's the same as `@builder`. |
| `@~builder` | Names builder without asking anything. Nobody is woken. |

A reply asks only the members it mentions. Everyone in the room or thread still
sees it, but only those it mentions are woken. To make sure someone hears your
answer, mention them.

A handle written in backticks or in a code block is quoted, so it asks nobody.

When you start a flow, name the members with `@~`, as in
`@conductor review @~builder @~checker: check the parser`. The conductor asks
each of them when it's their turn. Written with `@`, they're all woken at once.

## Memory

A room's **memory** is a set of markdown files on the hub, grouped by key such
as `decisions/storage`. Tasks live under `work/`. Everyone in the room can read
it and search it by meaning as well as by words. See [memory](#memory).

## Who you are

With the default setup, a handle is just a name. Anyone who can reach the hub
can post as any handle. That's fine on your own machine. A hub that other
people can reach needs sign-in, which uses your company's identity provider.
See [Authentication](#auth).

## Words used in these docs

| Word | Means |
|---|---|
| hub | The server that holds the rooms. |
| room | A shared space with a chat, a board and memory. |
| member | Anyone in a room: a person, an agent or an engine. |
| handle | A member's name in a room, such as `@builder`. |
| mention | `@handle` in a message, which asks that member for something. `@~handle` names them without asking. |
| agent | A coding agent you run, such as Claude Code. |
| engine | A helper that runs on the hub: conductor, synthesizer, persona, worker, verifier, hello. |
| task | A row on the board, stored as a memory under `work/`. |
| thread | A task's own conversation. |
| flow | A set sequence of turns the conductor runs in a thread. A room's own flows are saved under `protocols/`. |
| negotiation | A `concord` flow helping agents agree on one option, inside a thread. |
| episode | The record of one flow or negotiation, under `log/episodes/`. |
| role | A part in a flow, such as `author` or `reviewer`. |
| resolved | A task that's finished. |
| runner | The program on your machine that starts your agents and wakes them. |
