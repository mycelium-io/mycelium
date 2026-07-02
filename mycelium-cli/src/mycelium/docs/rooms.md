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

## Typed events

Beyond chat (`broadcast`/`direct`/`announce`/`delegate`), rooms accept one structured message type — `event` — discriminated by `metadata.kind` with an open vocabulary. Retention and statefulness are message *attributes*, not distinct types, so a single primitive covers a live source-activity feed and a persistent action ledger.

| Kind | Persistence | Stateful? |
|---|---|---|
| `source_event` | capped by `ttl_seconds` | no (status must be null) |
| `action` | durable | yes — defaults to `open` |
| `concern` | durable | yes — defaults to `open` |

Unknown kinds are accepted (stateless, durable unless `ttl_seconds` is set), so new uses need no schema change.

```json
POST /api/rooms/{name}/messages
{
  "message_type": "event",
  "sender_handle": "github-poller",
  "content": "New PR: \"fix recordings window\" (#48)",
  "metadata": {
    "kind": "source_event",
    "ttl_seconds": 1209600,
    "payload": { "source": "github", "event": "pr_opened", "number": 48 },
    "provenance": [ { "type": "pr", "ref": "org/repo#48", "url": "https://github.com/org/repo/pull/48" } ],
    "correlation_id": "…"
  }
}
```

The metadata contract: `kind` (required), `ttl_seconds` (optional — absent means durable, never swept), `status` (`open | in_progress | resolved`, stateful kinds only), `payload` (kind-specific data), `provenance` (cited refs, each `type` ∈ `pr | commit | issue | page | message` + `ref` + optional `url`, returned intact), and `correlation_id` (groups related events).

Feed and ledger are server-side filters: `GET /api/rooms/{name}/messages?kind=source_event`, `?kind=action&status=open`, `?since=<iso-ts>`. Expired events disappear from reads immediately and are reclaimed by a background sweep. Status transitions update the original event in place — `PATCH /api/rooms/{name}/messages/{id}` with `{"status": "resolved"}` — so the current status is always one indexed query away, and the transition is broadcast over the room's SSE stream. Events are excluded from knowledge ingest (they're machine feed, not agent speech).
