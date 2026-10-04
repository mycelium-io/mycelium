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
mentions and turns the same way any herdr agent does, because the runner keeps
it synced (see [The runner keeps your agents synced](#machines-the-runner-keeps-your-agents-synced)).

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
connected runners, what each found, the agents on it, and its recent
requests.

## The runner keeps your agents synced

An agent in herdr is a program in a terminal pane, and the hub can't see into
your machine. So something on the machine has to keep telling the hub whether
each agent is busy, and type a wake-up into an agent's pane when someone
mentions it. That is the runner's job, for every herdr workspace connected to
a room on this machine: the ones it opened, and any you connected yourself
with `mycelium herdr sync --workspace w2 --room my-project`.

While the runner isn't running, your agents keep working but don't hear their
mentions. The Mac app runs the runner for you.

A runner can also be running and stuck: connected to the hub, but with its
sync pass waiting on something that never answers. Every herdr and hub call it
makes has a time limit, and a pass that runs past 30 seconds is reported. The
Machines page and `mycelium machine` then say wakes have stalled, and for how
long, rather than that the runner is connected. Restarting the runner (or the
Mac app) gets wakes going again.

### What the runner did

The runner writes what it does to `~/.mycelium/runner/runner.log`, whether it
runs from the terminal or inside the Mac app: one line per wake (who, why,
which pane, how it went and how long it took), one per job and per question
asked here, herdr and hub calls that failed or were slow, and, for a stuck
sync pass, where every thread was. Times are UTC. The file rotates at 1 MB,
keeping three old ones.

```text
2026-10-04T09:19:02.114Z INFO    [runner-sync] wake @project-mgmt (mention) -> wQ:p1 ok 220ms
```

A runner started with `--detach` writes its terminal output, and a crash's
traceback, to `~/.mycelium/runner/runner.out`.

## Your agents on a machine

Every agent on a machine is listed in one place, whoever started it: the ones
the runner started, the ones `mycelium swarm` started, and panes you connected
to a room yourself. In the app, that's the Machines page:

![The Machines page: a machine's agent CLIs, its agents, and what to fix](app-machines.png)

From a terminal on that machine:

```bash
mycelium machine
```

It lists the agents by herdr workspace, says what each is doing, and then
what's wrong, with the command that fixes each. The Machines page shows the
same list for each connected machine. In the Mac app, **Your agents…** in the
menu bar opens it.

An agent is **working**, **idle** or **blocked** while it runs; **stopped**
when its pane is open with nothing running in it; or **pane gone** when the
pane was closed.

### When herdr restarts

Restarting herdr's server (to update it, say) stops every agent running in
it. herdr brings each one back in its own conversation if herdr's integration
for that agent CLI is installed. herdr has one for most agent CLIs, including
Claude Code, Codex, OpenCode and Pi. Without it, the panes come back empty and
the agents show as stopped.

```bash
mycelium machine integrations             # which are installed
mycelium machine integrations --install   # install them for the agent CLIs here
```

Installing one adds a hook to that agent CLI's own settings (for Claude Code,
`~/.claude/settings.json`), so Mycelium only does it when you say so. The Mac
app asks once. `mycelium machine` says, for each agent, whether it comes back
or stops if herdr restarts.

Mycelium needs herdr 0.9.3 or newer, and `mycelium machine` says how to update
an older one. The Mac app includes it.

### Restarting agents

An agent that stopped and didn't come back can be restarted. It starts again
in its own folder, as the same member, with no memory of what it was doing:
it reads its notes, then catches up from the room, which tells it what
happened since its last turn. This works the same for every agent CLI.

```bash
mycelium machine restart --all         # every stopped agent
mycelium machine restart reviewer      # one
```

On the Machines page, **Restart** says where each agent will start before
anything does. The runner then asks you on the machine, as it does before
starting any agent.

### Other fixes

```bash
mycelium machine rename reviewer "review"  # its name in herdr
mycelium machine unbind reviewer           # forget its pane; it stays in the room
mycelium machine unbind --gone             # forget every pane that's gone
```

Add `--json` to `mycelium machine` for the list as data.

## You say yes on the machine

Anyone who can reach a hub can ask it for an agent on any machine connected
to it, and the hub can't prove who asked. So the runner asks you before it
starts or restarts anything. It shows who the hub says asked, the agent CLI,
the folder, and the start of the agent's instructions:

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
