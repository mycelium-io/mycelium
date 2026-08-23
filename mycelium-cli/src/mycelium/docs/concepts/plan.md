# Plan

A room's **plan** is the place to write down what the room is for and what's
left to do. It lives in `~/.mycelium/rooms/{room}/plan/` as a small set of
markdown files, plus the `- [ ]` / `- [x]` checklist lines inside them.

Open tasks also appear on the [board](#board), next to open decisions and
whatever else currently needs a person.

Plan content is surfaced to every agent in the room, both in the turn the
[aligner](#aligner) addresses to them and in every agent-context briefing, so
agents weigh their behaviour against work that's already committed.

You can write the plan by hand (`plan set`, `plan task add`), but it also
fills itself: when an [episode](#episodes) converges on consensus, Mycelium
compiles the agreed `{issue: value}` map into `plan/tasks.md` automatically: a
`- [ ]` checklist with `@handle` owners that the whole team then executes
against. The plan is compiled *before* the consensus is announced, so it exists
the moment `await` returns. A re-negotiation updates that same plan, preserving
tasks already completed. The arc is **position → converge → plan → work**.

## Anatomy

```
.mycelium/rooms/{room}/plan/
├── title.md          # one-line italic display title (shown above room activity)
├── tasks.md          # default todo file written by `plan task add`
└── {slug}.md         # any number of additional plan files (prose + checklists)
```

`title.md` is special: its first non-empty line becomes the room's displayed
title (italic Cormorant Garamond in the UI, surfaced as a chip in the CLI).
All other `plan/*.md` files are arbitrary; they appear as chips in the room
header and as grouped task buckets in `plan tasks`.

## CLI

```bash
# Title
mycelium plan title                                # read
mycelium plan title "Plan the Q3 sprint priorities"  # set

# Files (each is a memory file under plan/<slug>)
mycelium plan ls
mycelium plan show sprint
mycelium plan set sprint "# Sprint\n\n- [ ] cut a release branch"
mycelium plan rm sprint

# Tasks (markdown checklist lines across every plan file)
mycelium plan tasks                  # open tasks only
mycelium plan tasks --all            # include completed
mycelium plan task add "ship the demo"          # appends to plan/tasks.md
mycelium plan task add "draft API" --file sprint # appends to plan/sprint.md
mycelium plan task done              # interactive multi-select over open tasks
mycelium plan task done tasks:3 sprint:7
mycelium plan task undo              # interactive multi-select over done tasks
```

Task IDs are `<slug>:<line>` and stable as long as the file isn't reflowed.

## How agents see it

Plan files share the same memory-style markdown-with-frontmatter convention,
so they live alongside `work/`, `decisions/`, etc. and are readable to anyone
opening the room directory.

During an episode, the open task list is also rendered into every agent's
turn under a dedicated **Open tasks** header, so an agent always negotiates
with the room's committed work in view.
