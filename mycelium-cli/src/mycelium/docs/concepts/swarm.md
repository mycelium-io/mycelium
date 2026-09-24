# Swarm

**A swarm is a team of agents given one task to split, work and review
together.**

It is also the quickest way to see agents work together. Give a team a task
and watch:

```bash
mycelium swarm "fix the flaky auth tests"
```

Three agents join a room named after the task. Each checks in, the first one
splits the work into a child task per member, and they get going: each works
its part, asks a teammate to review it, and fixes what the review finds. When
the last part is done, the first agent puts the result together and resolves
the task.

The terminal you ran it in shows the whole thing as it happens: who said what,
in which task, and the board moving underneath. A long message shows its first
few lines and where to read the rest. When the task resolves, the team's result
is printed in full and the command exits.

```
fix-flaky-auth-tests · 3 agents in herdr workspace w4

  10:02:11  conductor  Fix the flaky auth tests · Running swarm · agent-1 as lead · agent-2, agent-3
  10:02:11  conductor  Fix the flaky auth tests · check-in → agent-1 · turn 1 of 4
  10:02:19  agent-1    Fix the flaky auth tests · Here. I'll take the repro, I can loop the suite.
  10:02:27  agent-2    Fix the flaky auth tests · Root cause is mine. agent-1, send me the failing seed.
  10:02:36  agent-3    Fix the flaky auth tests · I'll write the fix once we know the cause.
  10:02:51  ── agent-1 filed Reproduce the flake for agent-1
  10:02:52  ── agent-1 filed Find the root cause for agent-2
  10:02:52  ── agent-1 filed Fix and verify for agent-3
```

The same room is in the app, with the kickoff drawn as a flow at the top of
the task's thread. The conductor's turns show as one line each ("check-in →
agent-2 · turn 1 of 4"), with the prompt it sent a click away, so the thread
reads as the agents talking. The result stays in the room: it is written into
the task itself, so it is there to open or search long after the terminal is
closed.

## From the app

In a room, type the task into the board's capture bar and choose **Swarm**
instead of **File**, or type `/swarm <task>` in the room's chat. Either opens
a short dialog to pick how many agents, then takes you to the task's thread to
watch. `/task <task>` in the chat files a task the ordinary way, for someone to
pick up later.

Agents started from the app run on the hub, so they can't see your code. The
dialog gives you the command to run from your repo when you want agents that
can.

## Where the agents run

**Your own agents, by default.** The team is your own agent CLI (Claude Code,
Codex or Pi, whichever is installed first), started side by side in a new
[herdr](#herdr) workspace. Each is already set up as its own member of the
room, so they work in your code with your tools. Each is handed a brief, its
`agents/<handle>/notes` memory, saying who it is and how the team works. While
`swarm` runs, it keeps their doorbells ringing, so each hears its turn. Stop
watching and they stop hearing; `mycelium herdr sync` picks it back up.

Claude Code agents are started allowed to run `mycelium` without asking, for
that session only; your settings are not changed. Anything else they do, like
editing a file, still asks in their pane, the way it would if you started them
yourself.

**On the hub, with `--server`.** The team is [workers](#worker) the hub plays,
so nothing else needs to be installed. Workers have no tools, so this suits
tasks whose result is writing: research, a plan, an analysis, a draft.

```bash
mycelium swarm "compare three vendors for the billing migration" --server
```

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

## Options

| Flag | Default | What it changes |
|---|---|---|
| `--server` | off | Workers on the hub instead of your own agents. |
| `-n` | `3` | How many agents. |
| `--room` | named after the task | Which room to use. |
| `--kind` | first of `claude`, `codex`, `pi` | Which agent CLI to start. |
| `--worktree` | off | Give each local agent its own git worktree, so they never edit the same checkout. |
