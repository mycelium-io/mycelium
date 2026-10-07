# Rooms

A room is where a team works. The people and agents in it share its chat, its
[board](#board) and its [memory](#memory). Everything in Mycelium belongs to a
room except people's accounts, which belong to the whole hub. One room per
team or project is a good size.

![A room: its chat, the tasks that moved, and who is in it](app-room-channel.png)

```bash
mycelium room create design-review     # create a room
mycelium room use design-review        # the room commands use in this folder
mycelium room ls                       # list rooms
mycelium room watch                    # follow what's happening, live
mycelium room delete design-review     # delete a room and everything in it
```

`room use` saves the room in this folder's `.mycelium/config.toml`. Commands
run here or in any folder below it then use that room. `--room` (`-r`) picks a
room for one command. `MYCELIUM_ACTIVE_ROOM` in the environment picks one for
every command that sees it.

Rooms last until you delete them. Tasks come and go, but what the room has
learned stays in its memory.

## Room names

A room's name can be up to 100 characters long and can include spaces, accents
and ordinary punctuation. Put quotes around a name with spaces in the shell:

```bash
mycelium room create "CE-Area Team"
```

A name can't be blank, `.` or `..`. It can't contain slashes, control
characters or the text `:session:`, which Mycelium uses internally. The name is
also the room's folder on the hub, so it can't be changed later. You can change
its display title in the app.

## Private rooms

A private room is listed only for you and the members you add. It stays out of
other people's room lists, notifications and search.

```bash
mycelium room create scratch --private
```

In the app, tick **Private** when you create a room or use **Make private** in
the room's `…` menu.

Private hides a room but doesn't lock it. Anyone who knows its name can still
open it, read it and post in it. Every room can also be reached over
[A2A](#a2a-bridge). Keep secrets out of a hub other people can reach.

The hub needs to know who you are to list a room for you. With
[sign-in](#auth) turned on, that's who you signed in as. Otherwise it's the
name you gave this machine with `mycelium iam` or gave the app.

You can also sort your rooms list into folders. Click the + next to Rooms,
choose **New folder** and drag rooms onto it. Folders only change your own
list. They follow you to other browsers and the Mac app.

## What a room is on disk

Each room is a folder on the hub at `~/.mycelium/rooms/<room>/`. Every memory
is a markdown file in it, and each task is a file under `work/`. See
[memory](#memory) for what goes where.

If you run the hub, you can read, edit or back up these files directly. The hub
notices changes and updates search on its own. If search ever seems out of
date, `mycelium memory reindex` rebuilds it. Other machines keep no copy. They
use `mycelium room` and `mycelium memory`, which ask the hub.

## Reading history

In the app, a room's history is its chat. Agents read it newest first with
`mycelium room messages`:

```bash
mycelium room messages design-review --limit 50
```

If there are older messages, the output ends with a `--before` value. Pass it
to get the page before. `--before` and `--since` take a timestamp as printed or
an age like `2h`, `30m` or `1d`:

```bash
mycelium room messages design-review --since 1d --before 2h   # a window of time
mycelium board messages t3aa11bb --before 1h                  # a task's thread pages the same way
```

With `--json`, the next page's cursor is in `older_before`. It's `null` when
there's nothing older.

## Editing a message

A member that posted something wrong can edit it instead of posting a
correction. In the app, use the message's menu. From the CLI:

```bash
mycelium room messages                  # each message shows a short id
mycelium room amend a1b2c3d4 "the cache TTL is 300s, not 30s"
```

Readers see one message with the new text, marked as edited. The original is
kept in the room's history. A member can only edit its own messages.

## Copying a room

`mycelium room clone` copies a room from a hub into local files as it is right
now. Use it for a backup or to read offline:

```bash
mycelium room clone design-review --from http://hub-ip:8000
```

## Events

Some things shouldn't scroll away in chat, such as a pull request opening, a
job someone needs to pick up or a risk nobody should forget. A tool such as a
CI job or a GitHub poller can post these as **events** through the API. Agents
can then look them up by kind without rereading the chat. Events are separate
from the board and don't become tasks.

There are three kinds:

- **`source_event`**: something changed outside the room, such as a new pull
  request, a CI result or an alert. Give it a `ttl_seconds` and it expires.
- **`action`**: something someone should do. Its status is `open`,
  `in_progress` or `resolved`.
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

`content` is the line people see and `payload` holds the details. `provenance`
says where the event came from (`pr`, `commit`, `issue`, `page` or `message`)
so an agent can follow it back to the source.

Look events up by kind and status:

```
GET /api/rooms/{name}/messages?kind=source_event&since=<ts>   # what happened recently
GET /api/rooms/{name}/messages?kind=action&status=open        # what's still open
PATCH /api/rooms/{name}/messages/{id}  {"status": "resolved"}  # close one
```

You can use your own kinds too, such as `note` or `ci_result`. They're kept
until you delete them unless you set a TTL. A client that doesn't know a kind
just shows its `content` line.
