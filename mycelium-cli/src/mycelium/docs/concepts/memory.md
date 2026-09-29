# Memory

A room's memory is the set of notes everyone in the room shares: decisions,
what's been tried, how things work, what people are doing. Each memory is a
markdown note with a key like `decisions/storage`. Agents and people read and
write them from the CLI, the chat or the app, and you can search them by
meaning, not just by exact words.

```bash
mycelium memory set decisions/storage "Rooms are folders; memory is markdown files"
mycelium memory get decisions/storage
mycelium memory search "how do we store things"
```

## What goes where

There are three places information can live:

1. **Your own notes.** Files your agent keeps for itself, like `SOUL.md` or
   its own notes, stay on your machine. They aren't shared or searchable by
   anyone else.
2. **Room memory.** What the whole team should know. Every member reads and
   writes it with `mycelium memory`, from any machine.
3. **The search index.** Built automatically from room memory so you can
   search it. You never write to it directly, and it can always be rebuilt
   from the notes.

A simple rule: if a teammate should be able to find it, put it in room memory.

## It lives on the hub

Room memory is stored on the hub. Other machines don't keep a copy. Every
`memory` command, including `get`, `ls`, `search` and the category views
(`memory decisions`, `status`, `work`, `context`, `procedures`), asks the hub
directly, and `memory set` writes straight to it.

So two machines always see the same thing. It also means memory commands need
the hub to be reachable. If it's down, or `server.api_url` points to the wrong
place, the command tells you rather than showing you something out of date.

```bash
mycelium config get server.api_url   # which hub this machine uses
mycelium status                      # is it up?
```

Every memory you write is indexed for search on the hub. The search model runs
locally and doesn't need an API key or any outside service.

## Naming keys

Keys use `/` to group related memories. The names are up to you, but these are
the usual ones, and they make `memory ls <prefix>/` handy:

```bash
# Decisions the team made
mycelium memory set "decisions/storage" "Rooms are folders; memory is markdown files"

# Things that didn't work, so nobody tries them again
mycelium memory set "failed/single-writer" "Serializing all writes stalled under load"

# What someone is working on (--handle says who wrote it)
mycelium memory set "status/prometheus" "Wiring up the aligner" --handle prometheus-agent

# List a group
mycelium memory ls decisions/
mycelium memory ls failed/
```

`memory set` on a key that already exists replaces it and bumps its version
number, so you can see how it changed.

Other useful options on `memory set`: `--file` (`-f`) reads the value from a
file (`-` for stdin), `--tags` (`-t`) adds comma-separated tags, and
`--no-embed` skips indexing it for search.

## How it's stored

On the hub, each memory is a markdown file with YAML frontmatter at
`~/.mycelium/rooms/{room}/{key}.md`, with the search index next to it. You
don't need to work with these files directly. Use `mycelium memory`, which
works the same on the hub and on every other machine.

To see a memory exactly as it's stored:

```bash
mycelium memory get decisions/storage --raw
```

### Your own fields

A few frontmatter fields are managed by Mycelium: `key`, who wrote it,
`version`, the timestamps, `tags` and `value`. Any other field is yours. Add
them with `--meta` (`-m`, repeatable), and they're kept when the memory is
updated later without them:

```bash
mycelium memory set work/api-server "Blocked behind the custody change" \
  -m status=open -m owner=@julia
```

They come back as `meta`, both in `--raw` and from the API (`MemoryRead.meta`):

```bash
curl -s $HUB/api/rooms/atlas/memory/work/api-server | jq .meta
# { "status": "open", "owner": "@julia" }
```

> **If you run the hub.** The memory files are ordinary files, so you can
> inspect them, back them up or edit them in bulk. Edits made outside
> Mycelium aren't in the search index until you run `mycelium memory reindex`.
> The index is also rebuilt when the backend starts, and it picks up file
> changes while it's running.

## Discussing a memory

Every memory has its own thread, the same kind of thread a [board](#board)
task has. So a discussion about a design note can stay with the note, instead
of scrolling past in the room:

```bash
mycelium board send context/api-shape "this predates the v2 routes, still true?"
mycelium board messages context/api-shape
```

These are the board's commands. They take a task, a thread id, or any memory
key. The room's chat only shows a short line saying the memory was discussed,
not the messages.

Any memory can be discussed, including the ones Mycelium writes itself, like
an `agents/` profile, a `log/` record or `context/synthesis`. But only memories
under `decisions/`, `status/`, `work/` and `failed/` show up on the board as
work to do. A `skills/` note with a thread won't appear there as something to
claim.

## Linking memories

Memories can link to each other, like pages in a wiki. There are two ways to
write a link, and they mean the same thing:

```markdown
We chose Postgres because of [[context/stack]].
We chose Postgres because of myc://context/stack.
```

`[[key]]` is the one you'll usually type. `myc://key` also works in
frontmatter and URLs. A link can point to a section and have its own text:

```markdown
[[context/stack#vector-store|how retrieval works]]
```

### Backlinks

Before you change a memory, check what links to it:

```bash
mycelium memory links context/stack
```

```
context/stack

→ links to
  ✓ procedures/deploy    wikilink

← referenced by (2)
  decisions/db           wikilink
  work/api-server        wikilink
```

To check the whole room for broken links, and for memories nothing links to:

```bash
mycelium memory links --check
```

In the app, `/room/{room}/graph` draws the room's memories as a graph, colored
by group, with broken links and unlinked memories marked. It's a good way to
see the overall shape of a room and what's been left hanging.

### Typed links

Some frontmatter fields are links with a specific meaning. Set them with
`--meta`:

```bash
mycelium memory set decisions/db "Postgres" -m supersedes=decisions/db-v1
```

The recognized ones are `supersedes`, `superseded-by`, `depends-on`, `part-of`
and `relates-to`. They show up in `memory links` along with links in the text.
On the board, `depends-on` also makes a task wait for another one (see
[board](#board)).

### Embedding one memory in another

A link sends the reader somewhere else. An embed copies the other memory's
text into the page when it's read, so a fact only has to be written once.
First, allow the memory to be embedded:

```bash
mycelium memory set glossary/vector-store \
  "fastembed ONNX, bge-small-en-v1.5, 384-dim, no external service." --expandable
```

Then embed it anywhere with `![[…]]`:

```markdown
Our retrieval layer is fixed:

![[glossary/vector-store]]
```

```bash
mycelium memory get decisions/db --expand
```

When you update the original, every page that embeds it shows the new text.

The rules:

- **Only memories marked `--expandable` can be embedded.** Embedding any other
  memory is reported as a broken link, not included.
- **Only one level deep.** If the embedded text has its own `![[…]]`, it's
  shown as written, not expanded. So embeds can't loop or grow without end.
- **Nothing is made up.** If an embed can't be expanded, the `![[…]]` is left
  as it is and reported, so it never looks like an empty definition.

Links only work within a room. `myc://rooms/{other}/{key}` is understood but
doesn't resolve to the other room.

Links are optional. A room whose memories don't link to each other works just
the same.

## Search

Search finds memories by what they mean, not just the words they use. It uses
the `BAAI/bge-small-en-v1.5` model (384 dimensions), which runs locally on the
hub with no outside service.

```bash
mycelium memory search "what storage decisions were made"
mycelium memory search "what failed and why"
mycelium memory search "what is the current status"
```
