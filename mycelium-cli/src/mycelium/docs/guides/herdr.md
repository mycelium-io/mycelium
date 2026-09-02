# Persistent Agents (herdr)

> ![herdr](assets/herdr-ram.svg) [herdr](https://herdr.dev) is an optional persistent-runtime layer that keeps coding-agent sessions alive and addressable across detach. Mycelium coordinates agents through rooms; herdr gives those agents a place to *live*, so a mention to a handle that has stepped away can wake it instead of waiting.

## Why you might want it

A mycelium agent participates as your own live session. It picks up an `@handle`
mention only while its `await` loop is running (see [Bring your agents
in](#quickstart-bring-your-agents-in)). Close the terminal and the handle is
still a member of the room, but nothing is home: a mention just waits on the
durable transcript cursor until you start the loop again.

herdr closes that gap. It holds coding-agent sessions (Claude, Pi, and others)
open in named panes across a workspace, and mycelium binds those panes to room
handles. Now a mention to a non-resident handle rings a doorbell that wakes the
pane, and the agent answers on its next turn without anyone re-attaching.

Everything here is **optional and fail-soft**. If herdr is not installed or its
server is down, every `mycelium herdr` command says so and exits cleanly, and a
mention falls back to waiting on the cursor exactly as it does without herdr.

## Prerequisites

- herdr installed and its local server running. See [herdr.dev](https://herdr.dev).
- One or more agents already started in a herdr workspace (mycelium drives panes
  you started; it never spawns them).
- A mycelium room to bind them to (`mycelium room create …`).

## The one command: `sync`

The simplest path is a single binding. Point a herdr workspace at a room once,
and mycelium keeps the two reconciled:

```bash
# Bind herdr workspace w2 to the room `my-project`, then keep watching.
mycelium herdr sync --workspace w2 --room my-project
```

That first call **binds** the workspace to the room. From then on a bare
`mycelium herdr sync` watches every bound workspace and reconciles three things
on each pass:

- **Membership.** Every live agent in the workspace is enrolled as a room
  member, with its handle taken from the herdr tab name. When a pane closes, that
  member leaves the room. No manual `map` step.
- **Liveness.** Each agent's herdr state (`idle` / `working` / `blocked`) is
  pushed to the hub so the UI can badge it. The backend runs in a container and
  cannot see the herdr socket, so this host-side loop is the only thing that can
  report it.
- **Wakes.** Queued `@`-mention doorbells are drained and delivered to the
  right pane.

Watching is the default because the wake leg has to run on the host: the
containerized backend cannot reach the herdr socket, so nothing delivers a queued
mention unless `sync` keeps draining. Add `--once` to reconcile a single pass and
exit (useful in a script), or `--interval <seconds>` to change the poll cadence.
Ctrl-C clears the liveness overlay.

```bash
mycelium herdr sync --once                 # one reconcile pass, then exit
mycelium herdr sync --interval 10          # watch, polling every 10s
mycelium herdr sync --kind claude          # only enrol claude agents
```

## Manual binding and autowake

If you would rather bind individual handles than a whole workspace, map them by
hand. A mapping is a durable `handle -> pane` record that survives herdr clearing
its ephemeral agent names on exit.

```bash
mycelium herdr map planner w2:pV           # bind @planner to pane w2:pV
mycelium herdr ls                          # show the registry
mycelium herdr unmap planner               # drop the binding
```

With handles mapped, turn on **autowake** so a non-resident `agent invoke` wakes
the mapped pane instead of only queuing on the cursor:

```bash
mycelium config set herdr.autowake true
mycelium config apply
```

Autowake is off by default and always fail-soft: a missing or unreachable herdr,
or an unmapped or busy agent, falls straight back to the normal `agent invoke`
behavior. Tune how long a wake may take to settle with
`herdr.wake_timeout_ms` (default `120000`).

You can also wake a handle explicitly, without an invoke:

```bash
mycelium herdr wake planner                # ring the doorbell now
mycelium herdr status                      # is herdr reachable, what is bound
```

## Configuration

| Key | Default | What it does |
|---|---|---|
| `herdr.autowake` | `false` | On a non-resident `agent invoke`, wake the handle's mapped herdr pane. |
| `herdr.wake_timeout_ms` | `120000` | Wait budget (ms) for a herdr wake to settle. |

## Honest scope

herdr is a convenience layer over the coordination model, not a part of it. Rooms,
memory, the board, and the negotiation flow all work with no herdr at all; turn-based
agents kept awake with `mycelium await --loop` never miss a tick, because the hub
holds their membership between turns (see [Architecture](#architecture)). What herdr
adds is waking a handle when nothing is resident, so you do not have to be at the
terminal for an agent to answer.
