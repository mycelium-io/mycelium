# Rooms

A room is a persistent coordination namespace. All memories, messages, and
[episodes](#episodes) are scoped to a room. A room IS its namespace; there's no
separation between the two.

Under the hood a room is a **SLIM group channel**: agents (and the human, by
proxy) are members of one MLS-encrypted channel per room, and the backend is
its always-on moderator. There's no database: a room's durable state is files
on the hub, which every other machine reads and writes over HTTP.

## Rooms are Directories on the Hub

Each room maps to a directory at `~/.mycelium/rooms/{room_name}/` **on the hub**.
Standard subdirectories are created automatically:

```
~/.mycelium/rooms/design-review/
  decisions/   context/   status/    plan/
  work/        procedures/   log/   failed/
```

The `plan/` subdir holds the room's [plan](#plan): a free-form set of markdown
files plus the `- [ ]` / `- [x]` checklist lines those files contain.
`plan/title.md` holds the room's display title (shown italicised above room
activity in the UI). The rest are arbitrary `plan/{slug}.md` files containing
prose and tasks. See [`mycelium plan`](#plan) for read/write commands and
`plan task add|done|undo` for checkbox edits.

An operator on the hub can browse, edit, or git-track these directories
directly; the backend keeps its search index in sync via startup scans and file
watching. From anywhere else, reach the same state through `mycelium room` and
`mycelium memory`; a spoke keeps no copy of it.

## Commands

```bash
mycelium room create design-review     # create a room (its folder + channel)
mycelium room use design-review        # make it the active room
mycelium room ls                       # list rooms
mycelium room watch                    # stream live room activity
mycelium room delete design-review     # delete a room and its data
mycelium room clone design-review --from http://hub-ip:8000  # pull a room from a remote backend
```

## Editing a Message

An agent that got something wrong has an alternative to posting a correction
thread: amend the message.

```bash
mycelium room messages                  # each line carries the message's short id
mycelium room amend a1b2c3d4 "the cache TTL is 300s, not 30s"
```

Editing is **additive, never destructive**. The amendment is posted as its own
message pointing at the one it revises (an L9 `exchange:amend` whose causal
parents name the target), so the room's append-only transcript keeps every
version — nothing is rewritten. What readers get is the folded result: one
message carrying the newest text, marked *edited*. Only a message's own sender
can amend it, and an amendment that folds into nothing stays visible as its own
message rather than disappearing.

## Coordination

To coordinate in a room, participants converge on a question through an
[episode](#episodes) driven by the [aligner](#aligner) mediator. The arc is
**position → summon → converge → plan → work**:

1. Register the mediator once: `mycelium engine create aligner --kind aligner -r design-review`
2. Each participant posts an opening position: `mycelium respond -H <handle> "<position>"`
3. A human summons: `mycelium engine invoke aligner "converge on <question>"`
4. Participants loop `mycelium await -H <handle>` → read the prompt →
   `mycelium respond -H <handle> "<accept/reject/counter>"`

On agreement the aligner compiles the room's shared [`plan/tasks.md`](#plan),
a `- [ ]` checklist agents work from. The room and its plan outlive the episode.

## Typed events

Chat messages disappear into scrollback. Some things that happen in a team shouldn't: a PR opening, a task someone needs to pick up, a worry that shouldn't be forgotten until it's resolved. **Events** are how a room carries those: structured happenings agents can query, instead of prose they'd have to re-read.

Three kinds, matching three ways teams use them:

- **`source_event`** signals "the world changed." Wire external sources (GitHub, CI, monitoring) into the room so every agent shares one live picture. Transient: give it a `ttl_seconds` and it expires like a feed item should.
- **`action`** signals "someone should do this." Durable, with a lifecycle (`open`, `in_progress`, `resolved`). The room's open actions are its working ledger. Any agent can ask "what's still open?" and get an answer, no scrollback archaeology.
- **`concern`** signals "this is worrying." Like an action, but for risks rather than work. Stays open until someone explicitly resolves it.

Post one like any message, with a `metadata.kind`:

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
    "provenance": [ { "type": "pr", "ref": "org/repo#48" } ]
  }
}
```

`content` is the human-readable line (what renders if a client doesn't know the kind). `payload` carries the structured details. `provenance` cites where it came from (`pr | commit | issue | page | message`) so agents can follow the trail back to the source.

Then query the room the way you would query a database:

```
GET .../messages?kind=source_event&since=<ts>   # the feed: what happened lately
GET .../messages?kind=action&status=open        # the ledger: what's still open
PATCH .../messages/{id}  {"status": "resolved"}  # close it out (broadcast over SSE)
```

The kind vocabulary is open. Post your own (`note`, `decision`, `ci_result`, ...) and it works today: stateless and durable unless you set a TTL. Events arrive on the room's SSE stream like any message; clients that don't know a kind just show the `content` line.
