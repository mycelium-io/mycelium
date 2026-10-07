# Memory

A room's memory is the set of notes everyone in the room shares: decisions,
what's been tried, how things work, what people are doing. Each memory is a
markdown note with a key like `decisions/storage`. People mostly read and
write it in the app; agents use the CLI:

```bash
mycelium memory set decisions/storage "Rooms are folders; memory is markdown files"
mycelium memory get decisions/storage
mycelium memory search "how do we store things"
```

You can search it by meaning, not just by exact words. The search model runs
on the hub, with no API key or outside service.

## What goes where

There are two places information can live:

1. **The agent's own files.** What a coding agent keeps for itself outside
   Mycelium, such as its `CLAUDE.md` or notes in its folder, stays on that
   machine. Nobody else sees it.
2. **Room memory.** What the whole team should know. Everyone in the room can
   read and search it, from any machine.

A simple rule: if a teammate should be able to find it, put it in room memory.

An agent's instructions in Mycelium are room memory too: they're saved as
`agents/<handle>/notes`, which anyone in the room can read and edit.

## Keys and folders

Keys use `/` to group related memories. The names are up to you, but these are
the usual ones:

| Folder | What's in it | On the board? |
|---|---|---|
| `work/` | Tasks. File them with `mycelium board new`. | Yes, as tasks |
| `decisions/` | Decisions the team made, and ones waiting on an answer | Yes |
| `status/` | Where something stands right now | Yes |
| `failed/` | Things that didn't work, so nobody tries them again | Yes, as blocked |
| `context/` | Background, preferences, and what engines save (summaries, decisions) | No |
| `procedures/` | Steps to repeat later | No |
| `agents/` | Each member's instructions | No |
| `protocols/` | The room's own [flows](#flows) | No |
| `log/` | Records of flows and negotiations | No |

```bash
mycelium memory set "failed/single-writer" "Serializing all writes stalled under load"
mycelium memory ls decisions/
```

`memory set` on a key that already exists replaces it and bumps its version
number. Other options: `--file` (`-f`) reads the value from a file (`-` for
stdin), `--tags` (`-t`) adds comma-separated tags, and `--no-embed` leaves a
memory out of search, for a large note you only ever read by key.

The [Structured Memory](#structured-memory) guide covers a habit for agents
writing these down as they work.

## It lives on the hub

Room memory is stored only on the hub. Every `memory` command asks the hub
directly, so two machines always see the same thing. If the hub can't be
reached, the command says so rather than answering from something out of date:

```bash
mycelium config get server.api_url   # which hub this machine uses
mycelium status                      # is it up?
```

On the hub, each memory is a markdown file with YAML frontmatter at
`~/.mycelium/rooms/{room}/{key}.md`, with the search index beside it. To see a
memory exactly as it's stored:

```bash
mycelium memory get decisions/storage --raw
```

> **If you run the hub.** The memory files are ordinary files, so you can
> inspect them, back them up or edit them in bulk. The hub picks up changes
> while it runs; `mycelium memory reindex` rebuilds search if it ever looks
> out of date.

### Your own fields

A few frontmatter fields are managed by Mycelium: `key`, who wrote it,
`version`, the timestamps, `tags` and `value`. Any other field is yours. Add
them with `--meta` (`-m`, repeatable), and they're kept when the memory is
updated later without them:

```bash
mycelium memory set work/api-server "Blocked behind the custody change" \
  -m status=open -m priority=high
```

They come back as `meta`, both in `--raw` and from the API.

## Discussing a memory

Every memory can have its own thread, the same kind a [board](#board) task
has, so a discussion about a design note stays with the note:

```bash
mycelium board send context/api-shape "this predates the v2 routes, still true?"
mycelium board messages context/api-shape
```

## Linking memories

Memories can link to each other, like pages in a wiki. These mean the same
thing:

```markdown
We chose Postgres because of [[context/stack]].
We chose Postgres because of myc://context/stack.
```

A link can point to a section and have its own text:
`[[context/stack#vector-store|how retrieval works]]`.

Before changing a memory, an agent can check what links to it:

```bash
mycelium memory links context/stack
mycelium memory links --check        # broken links, and memories nothing links to
```

In the app, `/room/{room}/graph` draws the room's memories as a graph.

Some frontmatter fields are links with a meaning: `supersedes`,
`superseded-by`, `depends-on`, `part-of` and `relates-to`. On the board,
`depends-on` also makes a task wait for another one.

```bash
mycelium memory set decisions/db "Postgres" -m supersedes=decisions/db-v1
```

Links only work within a room.

### Embedding one memory in another

An embed copies another memory's text into the page when it's read, so a fact
only has to be written once. Mark the memory as embeddable, then embed it with
`![[…]]`:

```bash
mycelium memory set glossary/vector-store "A local embedding model, no external service." --expandable
```

```markdown
Our retrieval layer:

![[glossary/vector-store]]
```

```bash
mycelium memory get decisions/db --expand
```

Only memories marked `--expandable` can be embedded, and only one level deep.
An embed that can't be expanded is left as written and reported as broken.
