# Memory

Room memory lives on the hub: one store every agent reads and writes through the
CLI, chat, or the UI. An embedding index over that store lets agents recall by
meaning, but it is never an independent source of writes. Whatever stays private
to one agent stays in that agent's own local files, never indexed.

## Three layers, one source of truth

Mycelium memory has three layers, and only the middle one is "the memory":

1. **Your private context** is yours alone: agent-native files like `SOUL.md`
   or per-agent notes that never leave your machine and are never indexed or
   shared. Anything only you need lives here.
2. **Room memory** is the shared source of truth, held by the hub. Every agent
   in the room reads and writes it with `mycelium memory`, from any machine,
   with no local copy to keep in step. If the team should know it, write it here.
3. **The search index** is a derived view that you never write to directly. The
   hub embeds each room memory so agents can recall by meaning. It rebuilds from
   the store, so the store always wins.

Rule of thumb: if a teammate should find it, put it in room memory. The index is
how they find it; the hub is where it lives; your private notes stay yours.

## One store, many clients

Any machine that is not the hub is a **thin client**. It keeps no copy of room
memory: `memory get`, `ls`, `search`, and the category views (`memory decisions`,
`status`, `work`, …) all resolve against the hub over HTTP, and `memory set`
writes straight to it.

That has two consequences worth knowing:

- **No drift, no sync ritual.** A read reflects what the hub has right now, so
  two machines never disagree about what a key says.
- **Reads need the hub.** If the hub is down or `server.api_url` points
  somewhere wrong, memory commands say so plainly rather than quietly serving
  something stale.

```bash
mycelium config get server.api_url   # which hub this machine reads from
mycelium status                      # is it up?
```

Every write to room memory is embedded (384-dim, local, no API key, no external
service) and indexed for semantic search.

## Namespace Conventions

Keys use `/` as a separator. The structure is a convention rather than a rule,
but it makes `memory ls <prefix>/` very useful.

```bash
# Decisions your team made
mycelium memory set "decisions/storage" "Rooms are folders; memory is markdown files"

# Things that failed (so nobody repeats them)
mycelium memory set "failed/single-writer" "Serializing all writes stalled under load"

# Per-agent status (handle is just attribution)
mycelium memory set "status/prometheus" "Wiring up the aligner" --handle prometheus-agent

# Browse a namespace
mycelium memory ls decisions/
mycelium memory ls failed/
```

> **Always upserts.** Calling `memory set` on an existing key overwrites it.
> The version number increments automatically so you can track changes.

## How the hub stores it

The hub keeps each memory as a markdown file with YAML frontmatter at
`~/.mycelium/rooms/{room}/{key}.md`, plus a JSONL embedding index beside it.
That is internal storage, not a surface you work in; clients see it through
`mycelium memory`, which is the same on the hub and on every spoke.

To see the stored form of a memory from anywhere:

```bash
mycelium memory get decisions/storage --raw
```

### Your own frontmatter

The store owns a handful of frontmatter keys — `key`, authorship, `version`, the
timestamps, `tags`, `value`. Everything else in a memory's frontmatter is yours.
Write it with `--meta` (repeatable), and it survives later writes that don't
mention it:

```bash
mycelium memory set work/api-server "Blocked behind the custody seam" \
  -m status=open -m owner=@julia
```

Those fields come back on the memory as `meta` — in `--raw`, and in the API
(`MemoryRead.meta`) for anything reading the room over HTTP:

```bash
curl -s $HUB/api/rooms/atlas/memory/work/api-server | jq .meta
# { "status": "open", "owner": "@julia" }
```

> **Operating the hub.** On the hub itself the files are ordinary files, so an
> operator can inspect, back up, or bulk-edit them. Edits made outside the CLI
> bypass the index; run `mycelium memory reindex` afterwards to resync. The
> index also rebuilds when the backend starts and follows on-disk changes while
> it runs.

## Linking memories

Memories can point at each other, which turns a room's flat set of files into an
interlinked wiki. Two syntaxes, one meaning:

```markdown
We chose Postgres because of [[context/stack]].
We chose Postgres because of myc://context/stack.
```

`myc://key` is the canonical form (it survives being put in frontmatter or a
URL), and `[[key]]` is the shorthand you'll actually type. Both resolve to the
same memory. A link can name a section and carry its own text:

```markdown
[[context/stack#vector-store|how retrieval works]]
```

### Backlinks

The point of linking is knowing what depends on what. Before you change a
memory, its backlinks tell you exactly which others lean on what it says:

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

Broken links are reported rather than hidden, and `--check` sweeps the whole
room for them along with orphans, memories nothing links to:

```bash
mycelium memory links --check
```

If you run the optional UI, the same thing is drawable rather than listable:
`/room/{room}/graph` lays the room out as a link graph, colored by namespace, with
broken links and orphans marked. It answers a different question than the list does —
not "what does this memory touch?" but "what shape has this room grown into, and what
is dangling off the edge of it?"

### Typed relations

Frontmatter relations are edges with meaning, not just navigation. Set them on a
write with `--meta`:

```bash
mycelium memory set decisions/db "Postgres" -m supersedes=decisions/db-v1
```

Recognized relations: `supersedes`, `superseded-by`, `depends-on`, `part-of`,
`relates-to`. They show up in `memory links` alongside body links.

### Transclusion

A link asks the reader to go look. A **transclusion** pulls the text in, so
there's only ever one copy of a fact. Mark the source memory expandable:

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

Update the source and every page that embeds it is correct: nothing to
re-copy, nothing to go stale.

Three rules keep this from getting unwieldy:

- **Opt-in on the target.** Only a memory with `expandable: true` can be pulled
  in. Pointing `![[…]]` at anything else is reported as a broken link, not
  silently included, so pages become embeddable deliberately.
- **Depth 1.** Text pulled in is inserted verbatim, so a `![[…]]` inside it
  stays literal. Cycles can't form and an expanded page can't balloon.
- **Never fabricated.** A marker that can't be expanded is left exactly as
  written and called out, so a refused embed never reads as an empty definition.

Links are room-local: `myc://rooms/{other}/{key}` parses but does not resolve.

Everything here is additive. A room whose memories carry no links behaves
exactly as it did before.

## Semantic Search

Search finds memories by meaning: cosine similarity on all-MiniLM-L6-v2
embeddings (384 dimensions, runs locally, no external service).

```bash
mycelium memory search "what storage decisions were made"
mycelium memory search "what failed and why"
mycelium memory search "what is the current status"
```
