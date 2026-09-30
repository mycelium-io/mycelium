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
else, and whether or not your laptop can be reached from outside. Before it
starts anything, it asks you (below).

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

In a room, open **Members → Add → Your machine**. The same dialog adds the
other kinds of member too: an engine the hub runs, an A2A service, or a
coding agent you already have open. For an agent on your machine, pick:

- **a role to start from** (reviewer, implementer, tester and so on), or a
  blank page. Instructions you write can be saved as a role of your own,
  kept in your browser;
- **a handle**, which is how the room addresses it (`@scout`);
- **instructions**, how the agent should work. They are saved as the
  agent's notes (`agents/<handle>/notes`), which it reads when it starts and
  you can edit later like any memory;
- along the bottom, **where it runs**: the machine (if more than one runner
  is connected), the agent CLI from what the scan found, and the folder it
  starts in.

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

## Starting agents in Omnigent instead

If you run agents with [Omnigent](https://github.com/omnigent-ai/omnigent),
the runner can start them there instead of in herdr:

```bash
mycelium config set runner.host omnigent
mycelium runner
```

This only works when Omnigent runs on the same machine as the runner. The
runner talks to the Omnigent server on this machine, at
`http://127.0.0.1:6767` by default. Start that server with `omnigent start`.
To use a different local address, set `runner.omnigent_url`.

The agents you can start are the ones Omnigent has ready on this machine.
Each agent runs as an Omnigent session, and you watch it and talk to it in
Omnigent's app. If the folder is a git repository, each agent gets its own
worktree, on a branch named `mycelium/<room>/<handle>`.

An agent needs to know which room it is in and which member it is. When the
runner starts an agent in herdr, it puts both in the agent's environment
variables. An Omnigent session is started by Omnigent, and the runner can't
set its environment. Instead, the runner gets a join code from the hub and
puts it in the agent's first message, which tells the agent to run
`mycelium join <code>` in its folder. See
[Joining a room from anywhere](#machines-joining-a-room-from-anywhere).

A swarm still starts in herdr, even with this setting.

## Joining a room from anywhere

When Mycelium starts an agent itself, it tells the agent which room it is in
and which member it is. An agent started some other way has no way to know
that. A join code gives it that information.

Whoever starts the agent asks the hub for a code. (The runner does this for
you when it starts agents in Omnigent.) The agent then runs:

```bash
mycelium join abcd-efgh-jkmn --hub http://your-hub:8000
```

A code works only once, and it expires after ten minutes.

Joining saves the membership in the current folder. The saved file is
readable only by you, and git ignores it. From then on, every `mycelium`
command run in that folder, or in any folder below it, acts as that member of
that room. If the hub has sign-in turned on, joining also gives the agent its
own token.

A folder holds one member. If the folder already belongs to another member,
`join` refuses unless you pass `--replace`. To remove the membership from a
folder, run `mycelium leave`.

To check which member a command in the current folder will act as, and why:

```bash
mycelium whoami --sources
```

It shows the hub, handle, room and credential in use, and where each one came
from. Mycelium checks these sources in order, and the first one that has a
value wins:

1. a flag on the command
2. the environment
3. this folder's `mycelium join`
4. this machine's setup

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

The Machines page (the laptop icon beside the notification bell) lists your
connected runners, what each found, the agents it is running, and its recent
requests.

## You say yes on the machine

Anyone who can reach a hub can ask it for an agent on any machine connected
to it, and the hub can't prove who asked. So the runner asks you before it
starts anything. It shows who the hub says asked, the agent CLI, the folder,
and the start of the agent's instructions:

- in the Mac app, as a dialog with **Start** and **Decline**;
- from a terminal, in the runner's output, answered with a command:

```bash
mycelium runner requests          # what is waiting
mycelium runner approve <id>      # start it
mycelium runner decline <id>      # don't
```

Nobody answering within ten minutes is a no. The app shows **Waiting for a
yes** until you answer, and says so when you decline.

One case doesn't ask: the Mac app's own hub. It listens only on your Mac, so
nobody else can reach it. A hub the app didn't start, such as a Docker one,
still asks. For a hub you know nobody else can reach, `mycelium runner
--trust-hub` skips the question.

## Only your machines are listed

The Machines page and **where it runs** show only your own machines, never
anyone else's. In the Mac app that is the Mac it runs on. In a browser, add a
machine with the code `mycelium runner` prints when it starts. With the hub's
[sign-in](#auth) turned on, the hub itself shows each person only the
machines they own.
