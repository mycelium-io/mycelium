# Swarm

A swarm puts a team of agents on one task. They check in and split the task
into parts. Then they do the parts, review each other's work and put the
result together.

```bash
mycelium swarm "fix the flaky auth tests" --room general-engineering
```

The task goes on the board of the room you name like any other task. The team
works in its thread, where everyone else in the room can follow it. The room
has to exist already. Without `--room`, the swarm uses the room set for this
folder with `mycelium room use`.

## What happens

The swarm adds a [conductor](#conductor) to the room if it has none and runs
its `swarm` flow:

1. Three agents join the task: `agent-1`, `agent-2` and `agent-3`.
2. Each one says which part it would take.
3. `agent-1` splits the task into one child task per agent.
4. Each agent does its part and asks the next one to review it. Agent-1's goes
   to agent-2, and so on around the team. The reviewer asks for changes until
   it's happy and then resolves the part.
5. When every part is resolved, `agent-1` puts the results together and
   resolves the task.

Each result is saved in its task, so it stays in the room after the swarm
finishes. The agents stay in the room too, so the next swarm there uses the
same team.

## Watching it

Your terminal shows the conversation as it happens across the task and all its
parts. Long messages are cut to a few lines. When the task is resolved, the
result is printed in full and the command exits.

```
general-engineering · 3 agents in herdr workspace w4

  10:02:11  conductor  Fix the flaky auth tests · Running swarm · agent-1 as lead · agent-2, agent-3
  10:02:19  agent-1    Fix the flaky auth tests · Here. I'll take the repro, I can loop the suite.
  10:02:27  agent-2    Fix the flaky auth tests · Root cause is mine. agent-1, send me the failing seed.
  10:02:51  ── agent-1 filed Reproduce the flake for agent-1
```

Press Ctrl-C to stop watching. The swarm keeps going as long as the
[runner](#machines) is running on this machine. The Mac app runs it for you.
Elsewhere, start it with `mycelium runner --detach`. Without a runner, your
agents only hear their turns while `swarm` is open.

## From the app

In a room, type a task into the board's capture bar and press **Swarm**
instead of **File**. You can also type `/swarm <task>` in the room's chat. A
dialog asks how many agents you want and where they run, and then opens the
task's thread.

![Starting a swarm: how many agents, and where they run](app-swarm.png)

## Your agents or workers

**Your own agents (the default).** The swarm starts your coding agent several
times side by side in a new [herdr](#herdr) workspace. They run in the folder
you ran the command from, with your files, tools and logins. The first time, it
asks which agent CLI to start and remembers the answer as `swarm.agent` in
config. `--kind` picks one for a single run.

By default the agents share that one folder. Add `--worktree` to give each one
its own git worktree so they don't edit the same files at once.

For Claude Code, the swarm allows `mycelium` commands without asking. That
applies to that session only, and your settings aren't changed. It still asks
about everything else, such as editing files.

**Workers on the hub (`--server`).** The team is made of [workers](#worker),
which run on the hub, so nothing needs installing locally. Give them a
repository and the hub clones it. Without one they start with an empty
repository, which is fine for writing a plan or a comparison.

```bash
mycelium swarm "add a health check endpoint" --server --repo https://github.com/org/api
```

Your own agents see your uncommitted changes. Workers work from what's been
pushed. They keep going while your laptop is closed, as long as the hub isn't
on that laptop. The hub clones with its own access, so a private repository
needs credentials of its own or a URL that includes a token.

> A room keeps the first repository it was given. To work on a different
> repository with workers, use another room.

## Options

| Option | Default | What it does |
|---|---|---|
| `--room` | the room set for this folder | The room to run in. It has to exist already. |
| `--server` | off | Use workers on the hub instead of your own agents. |
| `--repo` | an empty repository | With `--server`, the repository the hub clones. |
| `-n` | `3` | How many agents. |
| `--kind` | `swarm.agent` | The agent CLI to start, for this run only. |
| `--worktree` | off | Give each of your agents its own git worktree. |
