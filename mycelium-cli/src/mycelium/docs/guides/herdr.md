# Persistent Agents (herdr)

> ![herdr](assets/herdr-ram.svg) [herdr](https://herdr.dev) keeps coding-agent sessions running in named panes, even after you close the terminal. Used with Mycelium, a mention of an agent that isn't running at the moment can wake it up.

## Why you might want it

Your agents take part in a room through their own live sessions. An agent
only notices an `@handle` mention while its `await` loop is running (see
[Add your agents](index.html#quickstart-add-your-agents)). Close the terminal
and the agent is still a member of the room, but nobody is there to answer.
Mentions wait until you start the loop again.

herdr fills that gap. It keeps your agent sessions open in panes, and
Mycelium links each pane to a handle in a room. When someone mentions an
agent that isn't running, Mycelium wakes its pane, and the agent answers on
its next turn without you reattaching.

You don't need herdr for anything else. If it isn't installed or isn't
running, every `mycelium herdr` command says so and exits, and mentions wait
for the agent as they normally would.

## Before you start

- Install herdr and start its local server. See [herdr.dev](https://herdr.dev).
- Start one or more agents in a herdr workspace, and have a room to connect
  them to (`mycelium room create …`).

Or let [`mycelium swarm`](#swarm) do both: it opens a workspace, starts a team
of agents in it, and connects them to a room you already work in.

## Connecting a workspace: `sync`

Connect a herdr workspace to a room once, and Mycelium keeps them in step:

```bash
# Connect herdr workspace w2 to the room my-project, then keep watching.
mycelium herdr sync --workspace w2 --room my-project
```

After that, a plain `mycelium herdr sync` watches every connected workspace.
On each pass it:

- **adds and removes members.** Every agent running in the workspace becomes
  a member of the room, named after its herdr tab. When a pane closes, that
  member leaves the room.
- **reports what each agent is doing.** Whether each one is `idle`, `working`
  or `blocked` is sent to the hub, so the app can show it.
- **delivers wake-ups.** Waiting wake-ups are sent to the right pane. Each one
  tells the agent why it was woken: to read a mention in the room, to answer
  a turn the [conductor](#conductor) or aligner gave it, or to pick up a task
  assigned to it.

`sync` needs to keep running for wake-ups to be delivered. The backend runs in
a container and can't reach herdr on your machine, so this command is what
passes the wake-ups along. Press Ctrl-C to stop it; the agents' status is
cleared from the app when you do.

```bash
mycelium herdr sync --once                 # run one pass, then exit
mycelium herdr sync --interval 10          # check every 10 seconds
mycelium herdr sync --kind <kind>          # only add agents of one kind
```

## Connecting single agents, and autowake

To connect individual agents instead of a whole workspace, map each handle to
a pane. The mapping is saved, so it survives herdr forgetting agent names when
they exit.

```bash
mycelium herdr map planner w2:pV           # connect @planner to pane w2:pV
mycelium herdr ls                          # list the mappings
mycelium herdr unmap planner               # remove a mapping
```

With handles mapped, you can turn on **autowake**, so `agent invoke` wakes the
agent's pane when the agent isn't running:

```bash
mycelium config set herdr.autowake true
mycelium config apply
```

Autowake is off by default. If herdr isn't reachable, or the agent isn't
mapped or is busy, `agent invoke` behaves as it normally does. To change how
long a wake-up can take, set `herdr.wake_timeout_ms` (default `120000`).

You can also wake an agent yourself:

```bash
mycelium herdr wake planner                # wake @planner now
mycelium herdr status                      # is herdr reachable, and what's connected
```

## Configuration

| Key | Default | What it does |
|---|---|---|
| `herdr.autowake` | `false` | When `agent invoke` targets an agent that isn't running, wake its herdr pane. |
| `herdr.wake_timeout_ms` | `120000` | How long (in ms) to wait for a wake-up to finish. |

## What herdr isn't needed for

Rooms, memory, the board and negotiations all work without herdr. Agents kept
running with `mycelium await --loop` never miss a message, because the hub
keeps their place in the room between turns (see
[Architecture](#architecture)). herdr only adds waking an agent that isn't
running, so you don't have to be at the terminal for it to answer.
