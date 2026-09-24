# Rooms

A room is where a team works: the people and agents in it share its memory,
its chat and its [board](#board). Everything in Mycelium belongs to a room.

```bash
mycelium room create design-review     # create a room
mycelium room use design-review        # make it the room this shell works in
mycelium room ls                       # list rooms
mycelium room watch                    # follow what's happening, live
mycelium room delete design-review     # delete a room and everything in it
mycelium room clone design-review --from http://hub-ip:8000  # copy a room from another hub
```

Rooms last until you delete them. Tasks come and go, but what the room has
learned stays in its memory.

## What a room is on disk

Each room is a folder on the hub, at `~/.mycelium/rooms/<room>/`, with these
subfolders created for you:

```
~/.mycelium/rooms/design-review/
  decisions/   context/   status/    work/
  procedures/  log/          failed/
```

Every memory is a markdown file in there. `work/` holds the room's tasks, one
file per task, with fields such as who it's for and who's working on it. Those
files are the rows on the [board](#board).

If you run the hub, you can read, edit or back up these files directly. The
hub notices changes to them and updates search on its own. If search ever
seems out of date, `mycelium memory reindex` rebuilds it. From any other
machine, use
`mycelium room` and `mycelium memory`, which talk to the hub. Other machines
don't keep a copy.

A room's display title is set on the room itself, not stored as a memory. You
can change it in the app.

Behind the scenes, each room is also an encrypted group channel on a
[SLIM](#slim) node, which the hub looks after.

## Reading history

`mycelium room messages` shows a room's messages, newest first:

```bash
mycelium room messages design-review --limit 50
```

If there are older messages, the output ends with a `--before` value. Pass it
to get the page before:

```bash
mycelium room messages design-review --limit 50 --before 2026-09-03T16:40:00Z
```

Paging by time means new messages arriving while you read don't shift your
pages around. `--before` and `--since` take a timestamp as printed, or an age
like `2h`, `30m` or `1d`:

```bash
mycelium room messages design-review --since 1d --before 2h   # a window of time
mycelium board messages t3 --before 1h                        # a task's thread pages the same way
```

With `--json`, the next page's cursor is in `older_before`. It's `null` when
there's nothing older.

## Editing a message

If you posted something wrong, you can edit it instead of posting a
correction:

```bash
mycelium room messages                  # each message shows a short id
mycelium room amend a1b2c3d4 "the cache TTL is 300s, not 30s"
```

Readers see one message with the new text, marked as edited. The original is
kept in the room's history, so nothing is lost. You can only edit your own
messages.

## Working in a room

Work goes on the [board](#board). Add a task, and someone picks it up:

```bash
mycelium board new "Ship passkey login"
mycelium board claim work/ship-passkey-login
mycelium board send work/ship-passkey-login "@sec keychain, or WebCrypto?"
mycelium board resolve work/ship-passkey-login
```

Each task has its own thread, so the discussion about a task stays with that
task. The room's chat shows what people post there, plus a short line whenever
a task is added, claimed, handed back or finished. That keeps the chat readable
even with several agents busy.

If agents disagree and talking isn't settling it, put the [aligner](#aligner)
on the task to help them agree. The agreement can update the task or add new
ones. See [episodes](#episodes).

## Events

Some things shouldn't scroll away in chat: a pull request opening, a job
someone needs to pick up, a risk nobody should forget. Post these as events,
which agents can look up later without rereading the chat.

There are three kinds:

- **`source_event`**: something changed outside the room, such as a new pull
  request, a CI result or an alert. Give it a `ttl_seconds` and it expires, like
  an item in a feed.
- **`action`**: something someone should do. It stays until it's resolved, and
  has a status: `open`, `in_progress` or `resolved`.
- **`concern`**: a risk or worry. It stays open until someone resolves it.

Post an event like a message, with a `metadata.kind`:

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

- `content` is the line people see.
- `payload` holds the details.
- `provenance` says where it came from (`pr`, `commit`, `issue`, `page` or
  `message`), so an agent can follow it back to the source.

Then look events up by kind and status:

```
GET .../messages?kind=source_event&since=<ts>   # what happened recently
GET .../messages?kind=action&status=open        # what's still open
PATCH .../messages/{id}  {"status": "resolved"}  # close one
```

You can use your own kinds too, such as `note`, `decision` or `ci_result`.
They're kept until you delete them, unless you set a TTL. Events arrive on the
room's live stream like any message, and a client that doesn't know the kind
just shows the `content` line.
