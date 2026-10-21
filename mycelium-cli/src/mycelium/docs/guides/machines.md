# Start Agents From the App

The app can start coding agents on your own computer, one at a time or as a
swarm on a task. The program that does this is the **runner**, which runs on
that computer. The runner also wakes your agents when someone mentions them,
gives them a turn or assigns them a task.

The desktop app runs the runner for you. Anywhere else, start it and leave it
running:

```bash
mycelium runner --detach     # start in the background
mycelium runner status       # is it running, and does the hub see it?
mycelium runner stop         # stop it; agents it started keep running
```

While the runner isn't running, your agents keep working but don't hear about
mentions or turns.

The runner only ever connects out to the hub. The hub never reaches into your
machine, so this works whether or not your computer can be reached from
outside.

The runner looks on your `PATH` for the agent CLIs it knows, such as Claude
Code, Codex and OpenCode. It starts agents in [herdr](#herdr) terminals, and
needs herdr 0.9.3 or newer. The desktop app includes herdr. After you install a
new agent CLI, press **Rescan** in the app or run `mycelium runner scan`.

## Starting an agent

In a room, open **Members → Add → Your machine**. Start from a role or a blank
page, give the agent a handle, and write its instructions. The instructions are
saved in the room's memory as `agents/<handle>/notes`, and the agent reads them
when it starts. You can edit them later.

Press **Add to room**. The agent is added to the room and opens in a herdr
terminal.

Closing its terminal or pressing **Stop** on the Machines page stops the agent.
It stays in the room with its notes, so you can start it again.

### Agents start in auto mode

Claude Code and Codex agents that the app starts run in their CLI's own auto
mode. They work without asking you before each command.

- **Claude Code** starts with `--permission-mode auto`. It asks only when it
  judges an action risky.
- **Codex** starts with `--approve-for-me`. Its approval requests go to its own
  automatic review, inside its usual sandbox.

This applies to that session only. Your CLI settings aren't changed. Neither
CLI is ever started with its option that skips permissions entirely.

## Bringing in an agent that's already running

If you started an agent CLI in herdr yourself, open **Members → Add → Running
agent**. Pick the agent, check its handle, and press **Add to room**.

Your machine asks you first, because the runner is about to type into that
agent's terminal. Once the agent is idle, the runner types a short introduction
that names the room and the agent's handle. The agent keeps its own session.
Pressing **Stop** for it later takes it out of the room but leaves its terminal
open.

## A swarm on your machine

In the **Start a swarm** dialog, pick a connected machine under **Where**. The
team then runs as your own agent CLI in a new herdr workspace on that machine,
in the folder you choose. This is the same as running [`mycelium swarm`](#swarm)
in that folder.

## Which folders

The app can only start agents inside the folders the runner was given. A request
from the hub names an agent CLI and a folder, never a command to run.

By default the allowed folder is the one you ran `mycelium runner` from. Name
others with `--root`:

```bash
mycelium runner --root ~/code --root ~/work/api
```

In the desktop app, it's the working folder you chose at first run. You can
change it in Settings.

## You say yes on the machine

Anyone who can reach a hub can ask it to start an agent on any machine
connected to it, and the hub can't prove who asked. So before it starts
anything, the runner asks you on the machine. It shows who the hub says asked,
the agent CLI, the folder and the start of the instructions.

In the desktop app, a dialog offers **Start** and **Decline**. From a terminal:

```bash
mycelium runner requests          # what is waiting
mycelium runner approve <id>      # start it
mycelium runner decline <id>      # don't
```

If nobody answers within ten minutes, the answer is no.

The runner doesn't ask when the request comes from the desktop app's own hub,
because only this computer can reach that hub. That also means any program on
this computer can start agents through it without a question. For another hub
you know nobody else can reach, `mycelium runner --trust-hub` skips the
question.

## Pair a computer to skip approvals

Sometimes no one is at a machine to approve requests, as with a home server.
Pair the computer you work from with that machine. Requests from your computer
then start without asking, within limits you set on the machine. On the
machine:

```bash
mycelium runner pair --folder ~/code --cli opencode --days 30
```

This prints a code like `K7QM-4XHD-9RWA`. On your computer, open **Machines**,
click **Add machine → Pair** and enter the code. Check that both sides show the
same key fingerprint.

| Option | What it limits | Default |
|---|---|---|
| `--folder` | Folders agents can start in | all of the runner's folders |
| `--cli` | Agent CLIs it can start | any |
| `--swarms` | Whether swarms are allowed | no |
| `--days` | How long the pairing lasts (`0` means no expiry) | 90 |

A request outside these limits, or from another computer, still asks. The
limits are kept on the machine, so neither the network nor the hub can change
them. `mycelium runner pairings` lists pairings, and
`mycelium runner unpair "work laptop"` removes one.

## Only your machines are listed

The Machines page, behind the laptop icon beside the bell, shows only your own
machines. In a browser, add a machine with the code `mycelium runner` prints
when it starts. With the hub's [sign-in](#auth) on, the hub shows each person
only the machines they own.

To see and fix the agents already running on a machine, see
[Your agents on a machine](#agents-on-a-machine).
