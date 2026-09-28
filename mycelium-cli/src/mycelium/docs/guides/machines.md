# Start Agents From the App (runner)

The app can start coding agents on your own computer: one agent with its own
instructions, or a whole swarm on a task. To let it, run the **runner** on
that computer.

```bash
mycelium runner
```

Leave it running. It looks for the agent CLIs installed on the machine, tells
the hub what it found, and starts agents in [herdr](#herdr) when someone asks
for one from the app. Agents it starts are ordinary interactive sessions in
herdr panes, so you can watch them work and type to them.

## How it connects

The runner only ever connects out to the hub. The app never talks to your
machine directly: it asks the hub, and the hub hands the request to the
runner the next time the runner checks in (a few seconds at most). So it
works the same whether the hub is on your laptop or on a server somewhere
else, and whether or not your laptop can be reached from outside.

## What it finds

On start, and whenever you press **Rescan** in the app, the runner checks
your `PATH` for the agent CLIs it knows (Claude Code, Codex, Gemini CLI,
Cursor Agent, OpenCode, Pi, GitHub Copilot CLI, Amp and others). Which of them
it can start is up to herdr: the runner asks herdr which agent kinds it
supports, so a newer herdr can start more of them with no change to Mycelium.

See the same list from a terminal:

```bash
mycelium runner scan
```

herdr is required. Without it the runner still connects and reports what it
found, but the app can't start anything on that machine and says so.

## Starting an agent

In a room, open **Members → Invite → Agent on your machine**. Pick:

- **the machine**, if more than one runner is connected;
- **the agent CLI**, from what the scan found;
- **a handle**, which is how the room addresses it (`@scout`);
- **instructions**, how the agent should work. They are saved as the
  agent's notes (`agents/<handle>/notes`), which it reads when it starts and
  you can edit later like any memory;
- **the folder** it starts in.

The agent is added to the room first, then started. It opens in a herdr
pane, reads its notes, and looks at the board. From then on it hears
mentions and turns the same way any herdr agent does. The runner keeps
`herdr sync` running for the agents it started, so you don't need a separate
terminal for that.

Closing the pane, or pressing **Stop** on the Machines page, stops the agent
but leaves it in the room with its notes. Starting it again from the app picks
up where its notes leave off.

## A swarm on your machine

The **Start a swarm** dialog has a **Where** choice. Pick a connected machine
instead of the hub, and the team is your own agent CLI in a new herdr
workspace on that machine, started in the folder you choose (optionally with a
git worktree per member). It is the same as running `mycelium swarm` in that
folder, without the terminal.

## Which folders

The app can only start agents inside the folders the runner was given, and
only with an agent CLI the scan found. It never sends a command to run. By
default the allowed folder is the one you ran `mycelium runner` from; name
others with `--root`:

```bash
mycelium runner --root ~/code --root ~/work/api
```

## Running it in the background

```bash
mycelium runner --detach     # start in the background
mycelium runner status       # is it running, and does the hub see it?
mycelium runner stop         # stop it; agents it started keep running
```

The Machines page (the laptop icon beside the notification bell) lists every
connected runner, what it found, the agents it is running, and its recent
requests.

## Who can use it

A runner does what the hub asks. With the hub's
[sign-in](#auth) turned off, anyone who can reach the hub can start agents on
a connected machine, within its folders and its scan. On a shared or public
hub, turn sign-in on before connecting a runner.
