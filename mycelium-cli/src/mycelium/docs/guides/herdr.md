# Persistent Agents (herdr)

[herdr](https://herdr.dev) keeps coding-agent sessions running in named
terminals (panes), even after you close the window you started them from.
Mycelium uses it to run your agents and to wake them when the room needs them.
The Mac app includes it; elsewhere, install herdr 0.9.3 or newer from
[herdr.dev](https://herdr.dev) and start its server.

You don't need to set herdr up by hand if you start agents from the app or with
`mycelium swarm`: both open a herdr workspace, connect it to the room, and the
[runner](#machines) keeps it in step. This guide is for connecting agents you
started in herdr yourself.

## Why it matters

An agent that runs `mycelium await --loop` hears about each message on its own:
the hub keeps its place in the room, so it never misses one. But a coding
agent sitting idle at its prompt isn't asking. herdr plus the runner fill that
gap: when the agent is mentioned, given a turn by the conductor or aligner, or
assigned a task, the runner types a wake-up into its pane saying why, and the
agent answers on its next turn without you being at the terminal.

Rooms, memory, the board and negotiations all work without herdr. It only adds
waking an agent that isn't already asking.

## Connecting a workspace

Connect a herdr workspace to a room once:

```bash
mycelium herdr sync --workspace w2 --room my-project
```

From then on the runner keeps every connected workspace in step, every few
seconds:

- **Members.** Every agent running in the workspace becomes a member of the
  room, with a handle taken from its herdr tab's name (plus the pane's id when
  two share a name; `--name-from pane` uses the pane id alone). When its pane
  closes, that member leaves the room. (Agents the app started work differently: closing their pane stops them
  but keeps them in the room, so you can start them again.)
- **Status.** Whether each agent is `idle`, `working` or `blocked` is sent to
  the hub, so the app can show it.
- **Wake-ups.** Waiting wake-ups are typed into the right pane.

`mycelium herdr sync` also runs one pass straight away and says whether the
runner is running. Make sure it is (`mycelium runner --detach`; the Mac app runs
it for you), or nothing is delivered after that first pass.

```bash
mycelium herdr sync                        # one pass over every connected workspace
mycelium herdr sync --kind claude          # only add agents of one agent CLI
mycelium herdr unbind w2                   # stop syncing w2; its agents stay in the room
```

A workspace that fails to sync doesn't hold up the others. `mycelium machine`
names the one that failed and why.

## Connecting a single agent

To connect one agent instead of a whole workspace, map its handle to its pane:

```bash
mycelium herdr map planner w2:pV           # connect @planner to pane w2:pV
mycelium herdr ls                          # list the mappings
mycelium herdr unmap planner               # remove a mapping
mycelium herdr wake planner                # wake @planner now
```

`mycelium agent invoke planner "…"` posts a message to `@planner` from the
command line. With `herdr.autowake` on, it also wakes the agent's pane straight
away from this machine, rather than waiting for the runner:

```bash
mycelium config set herdr.autowake true
mycelium config apply
```

## Configuration

| Key | Default | What it does |
|---|---|---|
| `herdr.autowake` | `false` | `agent invoke` wakes a mapped agent's pane directly. |
| `herdr.wake_timeout_ms` | `120000` | How long (in ms) to wait for a wake-up to finish. |
| `herdr.panes_per_tab` | `4` | How many agents share a tab in a room's workspace. A new agent splits the largest pane in half; past this many, it opens a new tab. |

To bring agents back after herdr's server restarts, see
[Your agents on a machine](#agents-on-a-machine).
