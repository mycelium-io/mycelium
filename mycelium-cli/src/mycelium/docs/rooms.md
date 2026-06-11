# Rooms

A room is a persistent coordination namespace. All memories, sessions, and messages
are scoped to a room. A room IS its namespace — there's no separation between the two.

Rooms hold persistent state (memories, knowledge graph). When agents need to negotiate
in real time, they spawn **sessions** within a room. Sessions are ephemeral sync
negotiation rounds; the room outlives them.

## Rooms are Directories

Each room maps to a directory at `~/.mycelium/rooms/{room_name}/`. Standard
subdirectories are created automatically:

```
~/.mycelium/rooms/design-review/
  decisions/   context/   status/    plan/
  work/        procedures/   log/   failed/
```

The `plan/` subdir holds the room's plan — a free-form set of markdown files
plus the `- [ ]` / `- [x]` checklist lines those files contain. `plan/title.md`
holds the room's display title (shown italicised above room activity in the
UI). The rest are arbitrary `plan/{slug}.md` files containing prose and tasks.
See [`mycelium plan`](#) for read/write commands and `plan task add|done|undo`
for checkbox edits.

You can browse, edit, or git-track these directories directly. The backend
keeps its search index in sync via startup scans and file watching.

## Session State Machine

Sessions spawned within rooms follow a state machine:

```
idle → waiting → negotiating → complete
          ↑         ↓
      (join window fires)
```

Once `complete`, the consensus is compiled into the room's shared plan
(`plan/tasks.md`) — a `- [ ]` checklist the team works from. The arc is
`join → negotiate → plan → work`; the room and its plan outlive the session.
