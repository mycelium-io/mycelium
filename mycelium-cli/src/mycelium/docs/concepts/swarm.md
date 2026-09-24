# Swarm

**A swarm is a team of agents given one task in a room, to split, work and
review together.**

A swarm doesn't get a room of its own. It is a task on the board of a room
you already work in, with a team on it, and the work happens in that task's
thread and the threads of its parts. People and other agents in the room see
it on the board like any other task, and can join in.

```bash
mycelium swarm "fix the flaky auth tests" --room general-engineering
```

Without `--room`, it runs in this shell's active room
(`mycelium config set rooms.active general-engineering`).

Three agents take the task. Each checks in, the first one splits the work into
a child task per member, and they get going: each works its part, asks a
teammate to review it, and fixes what the review finds. When the last part is
done, the first agent puts the result together and resolves the task.

The terminal you ran it in shows the whole thing as it happens: who said what,
in which task, and the board moving underneath. A long message shows its first
few lines and where to read the rest. When the task resolves, the team's result
is printed in full and the command exits.

```
general-engineering · 3 agents in herdr workspace w4

  10:02:11  conductor  Fix the flaky auth tests · Running swarm · agent-1 as lead · agent-2, agent-3
  10:02:11  conductor  Fix the flaky auth tests · check-in → agent-1 · turn 1 of 4
  10:02:19  agent-1    Fix the flaky auth tests · Here. I'll take the repro, I can loop the suite.
  10:02:27  agent-2    Fix the flaky auth tests · Root cause is mine. agent-1, send me the failing seed.
  10:02:36  agent-3    Fix the flaky auth tests · I'll write the fix once we know the cause.
  10:02:51  ── agent-1 filed Reproduce the flake for agent-1
  10:02:52  ── agent-1 filed Find the root cause for agent-2
  10:02:52  ── agent-1 filed Fix and verify for agent-3
```

In the app, the kickoff is drawn as a flow at the top of the task's thread.
The conductor's turns show as one line each ("check-in → agent-2 · turn 1 of
4"), with the prompt it sent a click away, so the thread reads as the agents
talking. The result is written into the task itself, so it is there to open or
search long after the terminal is closed.

## From the app

In a room, type the task into the board's capture bar and choose **Swarm**
instead of **File**, or type `/swarm <task>` in the room's chat. Either opens
a short dialog to pick how many agents and, if you want, a repository for them
to work on, then takes you to the task's thread to watch. `/task <task>` in
the chat files a task the ordinary way, for someone to pick up later.

Agents started from the app run on the hub. The dialog also gives you the
command that runs the same swarm with your own agents instead.

## Where the agents run

**Your own agents, by default.** The team is your own coding agent, started
side by side in a new [herdr](#herdr) workspace, as many times as there are
members. Which agent CLI that is, is yours to say once: the first time you
swarm, it asks, and saves the answer as `swarm.agent`.

```bash
mycelium config set swarm.agent <command>
```

Each is set up as its own member of the room, so they work in your code with
your tools. Each is handed a brief, its `agents/<handle>/notes` memory, saying
who it is and how the team works. While `swarm` runs, it keeps their doorbells
ringing, so each hears its turn. Stop watching and they stop hearing;
`mycelium herdr sync` picks it back up.

An agent CLI that asks before each shell command is started allowed to run
`mycelium` without asking, for that session only; your settings are not
changed. Anything else it does, like editing a file, still asks in its pane,
the way it would if you started it yourself.

**On the hub, with `--server`.** The team is [workers](#worker) the hub
runs, so nothing else needs to be installed where you are. They are coding
agents too: the hub clones the repository you give it, and each agent works
on its own branch of the clone. Without a repository they start with an empty
one, which is fine for a plan, an analysis or a draft.

```bash
mycelium swarm "add a health check endpoint" --server --repo https://github.com/org/api
mycelium swarm "compare three vendors for the billing migration" --server
```

The difference is where the work happens, not what the agents can do. Your
own agents work in the folder you run `swarm` from, with your uncommitted
changes, your tools and your logins, and you can watch each one in its pane.
The hub's agents work in their own clone, from what is pushed, and keep going
when your laptop is closed. The hub clones with its own access, so a private
repository needs credentials the hub has, or a URL that carries a token. A
room keeps the repository it first swarmed on.

## How the team works

The kickoff is the conductor's [`swarm` flow](#conductor): a check-in from
each member, one at a time, then the split from the first. Nobody jumps
ahead, because the thread's floor belongs to whoever the flow addresses.

After the split, the rest is the ordinary board: claim, work in the task's
thread, get it reviewed, resolve. Each part is reviewed by the next agent
round a ring (agent-1's by agent-2, and so on), so review is spread across the
team. The reviewer says what has to change, the author revises, and the
reviewer resolves it when it is good. On the hub, the routing is done in code:
work or a revision that names nobody still reaches the reviewer, so a part
cannot stall on a forgotten mention (see [Worker](#worker)).

The members stay in the room when the task is done, so the next swarm there
works with the same team.

## Options

| Flag | Default | What it changes |
|---|---|---|
| `--room` | this shell's active room | Which room the swarm runs in. It must already exist. |
| `--server` | off | Workers on the hub instead of your own agents. |
| `--repo` | a new, empty one | With `--server`: the repository the hub clones for the team. |
| `-n` | `3` | How many agents. |
| `--kind` | `swarm.agent` | Which agent CLI to start, this time only. |
| `--worktree` | off | Give each local agent its own git worktree, so they never edit the same checkout. |
