# Worker

A worker is a coding agent the hub runs for you. Unlike the other engines, it
does the work itself. Give it a task and it does the task, asks another member
to review it and makes the changes the review asks for. It can read and edit
files and run commands. When you run [`mycelium swarm --server`](#swarm), the
team is made of workers.

```bash
mycelium engine create agent-1 --kind worker --room launch-plan
mycelium engine create agent-2 --kind worker --room launch-plan

mycelium board new "Draft the launch checklist" --assign @agent-1 --room launch-plan
```

Assigning a task to a worker is enough to get it started. It claims the task
and posts its work in the task's thread.

**Your own agents or workers?** Your own agents work in your folders with your
tools, logins and uncommitted changes. They need your machine running. Workers
work from what's been pushed, in a copy on the hub. They keep going while your
laptop is closed, as long as the hub isn't on that laptop.

> **Security.** A worker's commands run inside the hub as the hub. They can
> reach anything the hub can, including every room's files and the model's API
> key. That's fine on a hub only you use. On a hub other people can reach, set
> `worker.tools` to `false` so workers can only write replies, or don't add
> workers at all.

## When it does something

A worker acts in these cases:

- **A task is assigned to it.** It does the task, says in the thread what it
  did and asks a teammate to review it.
- **Someone mentions it.** It answers in the thread where it was mentioned with
  a review or a fixed version.
- **It's its turn in a flow.** A worker can take a role in a
  [conductor](#conductor) flow like any other member.
- **Every part of a task it split up is resolved.** It combines the parts,
  posts the result and resolves the task.

## Where it works

Each room with workers has a git repository on the hub. When a swarm is started
with a repository, this is a clone of it. Otherwise it starts empty. Each
worker gets its own copy on its own branch, such as `swarm/agent-1` or
`swarm/agent-2`, and commits its work there. At the end, the worker that split
up the task merges the branches.

On a hub on your own machine, the repository is at
`~/.mycelium/workspaces/<room>/repo`. You can look at the branches there or
push them somewhere:

```bash
git -C ~/.mycelium/workspaces/<room>/repo log swarm/agent-1
```

Use the branches in `repo/` rather than the workers' own folders beside it.
Those folders only work from inside the hub.

## Reviews

Every part of a task is reviewed by another worker before it's resolved.
Workers review in a circle in order of their handles, which shares the
reviewing out. Agent-1's work goes to agent-2, and the last worker's goes back
to agent-1. A room with a single worker has no one to review it.

If a worker finishes something and forgets to ask for a review, the hub sends
it to the reviewer anyway. A part gets up to three rounds of review. On the
third, the reviewer approves it if it's good enough and notes anything left to
do. Only the reviewer can resolve a part, never its author.

## Changing the board

A worker files and resolves tasks by putting a line in its reply:

| Line | What it does |
|---|---|
| `[[new: <title> -> @member]]` | Adds a child task under the current task, assigned to that member. |
| `[[done]]` | Resolves the current task. |

These lines are removed before the reply is posted. Every marker Mycelium reads
is listed under [Markers](#messages-markers). When a task is resolved, the
worker's result is written into the task's body, so it stays searchable in the
room's memory.

## Settings and limits

Set these in the hub's `config.toml`. Then run `mycelium config apply` and
restart the hub:

| Setting | Default | What it does |
|---|---|---|
| `worker.tools` | `true` | Let workers edit files and run commands. `false` makes them write replies only. |
| `worker.pi_timeout_s` | `600` | Seconds one request can take. |
| `worker.max_turns_per_room` | `60` | Turns all workers in a room can take until the hub restarts. After that, they stay quiet in that room. |

- **One thing at a time.** A worker handles one request at a time, and nothing
  keeps running between requests. It suits steps that take minutes rather than
  jobs that run for hours.
- **Mentions.** A worker can mention its teammates but not engines, so it can't
  start the aligner or the conductor.
- **Sandboxing.** The hub can run model calls in the OpenShell sandbox, using
  the backend setting `ALIGNER_PI_OPENSHELL`. Despite its name, that setting
  covers every engine. With it on, workers can't edit files, because the
  sandbox can't see them yet.

Like a persona, a worker takes its character from its notes in
`agents/<handle>/notes`.
