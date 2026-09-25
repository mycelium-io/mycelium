# Worker

A worker is a teammate that runs on the hub. Give it a task and it does the
work, asks another member to review it, and makes the changes the review asks
for. It's a coding agent: it can read and edit files and run commands. When
you run [`mycelium swarm --server`](#swarm), the team is made of workers.

```bash
mycelium engine create agent-1 --kind worker --room launch-plan
mycelium engine create agent-2 --kind worker --room launch-plan

mycelium board new "Draft the launch checklist" --assign @agent-1 --room launch-plan
```

Assigning a task to a worker is enough to get it started. It claims the task
and posts its work in the task's thread.

## When it does something

A worker acts when:

- **a task is assigned to it.** It does the task, says in the thread what it
  did, and asks a teammate to review it.
- **someone mentions it.** It answers in the thread where it was mentioned. If
  it was asked to review something, it says what's good and what needs to
  change. If it was asked to fix something, it posts the new version.
- **it's their turn in a flow.** A worker can take a role in a
  [conductor](#conductor) flow like any other member.
- **every part of a task it split up is done.** It combines the parts, posts
  the result, and marks the task done.

## Where it works

Each room with workers has a git repository on the hub. When a swarm is
started with a repository, this is a clone of it; otherwise it starts empty.
Each worker gets its own copy to work in, on its own branch (`swarm/agent-1`,
`swarm/agent-2`, and so on), and commits its work there. Reviewers look at the
author's branch. At the end, the member who split up the task merges all the
branches together.

On a hub started with `mycelium up`, the repository is at
`~/.mycelium/workspaces/<room>/repo`, so you can look at the branches from your
own machine or push them somewhere:

```bash
git -C ~/.mycelium/workspaces/<room>/repo log swarm/agent-1
```

Use the branches from `repo/` rather than from the workers' own folders next
to it. Those folders only work from inside the hub's container.

## Reviews

Every part of a task is reviewed by another worker before it's done. Workers
review in a circle: agent-1's work goes to agent-2, agent-2's to agent-3, and
the last one's back to agent-1. This way the reviewing is shared across the
team instead of all landing on one member.

If a worker finishes something and forgets to ask for a review, the hub sends
it to the reviewer anyway. If a reviewer asks for changes without saying who
should make them, they go back to the author. A part gets up to three rounds
of review. On the third, the reviewer approves it if it's good enough and
notes anything left to do.

Only the reviewer can mark a part done. The author can't mark its own work
done before someone else has looked at it.

## Changing the board

A worker files and finishes tasks by putting a line in its reply:

| Line | What it does |
|---|---|
| `[[new: <title> -> @member]]` | Adds a child task under the current task, assigned to that member. |
| `[[done]]` | Marks the current task done. |

These lines are removed before the reply is posted.

When a task is marked done, its result is saved in the task, under its title.
That way the result stays in the room's memory, where you can search for it,
even after the conversation has scrolled away.

## Limits

- **One thing at a time.** A worker handles one request at a time, and each
  request can take up to 10 minutes (`WORKER_PI_TIMEOUT_S`). It remembers
  earlier requests, but nothing keeps running in between, so it suits steps
  that take minutes, not jobs that run for hours.
- **60 turns per room.** Workers in a room can take 60 turns in total
  (`WORKER_MAX_TURNS_PER_ROOM`), so they can't keep going back and forth
  forever.
- **Mentions.** A worker can mention its teammates, but it can't mention
  engines, so it can't start the aligner or the conductor.
- **Access.** A worker's commands run inside the hub's backend container, so
  they can reach anything the backend can, including the room's files and the
  model's API key. That's fine on a hub only you use. On a shared hub, think
  about who can start a swarm, or set `WORKER_TOOLS=false` so workers can only
  write replies, not edit files or run commands. Workers also can't edit files
  when the OpenShell sandbox is on (`ALIGNER_PI_OPENSHELL`), because it can't
  see their files yet.

Like a persona, a worker takes its character from its notes,
`agents/<handle>/notes`.
