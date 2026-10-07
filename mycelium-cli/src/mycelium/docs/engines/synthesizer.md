# Synthesizer

The synthesizer reads what's been said in the room, task threads included, and
writes a summary into the room's memory. Decisions often get made in
conversation and then scroll away; the synthesizer writes them down where they
can be found later.

```bash
mycelium engine create synthesizer --kind synthesizer --room sprint-plan

# Summarize what's been said since the last time
mycelium engine invoke synthesizer "catch us up" -r sprint-plan

# Read the summary
mycelium memory get context/synthesis -r sprint-plan
```

In the app, mention it in the chat (`@synthesizer catch us up`), or use **+**
and **Catch up**, which calls it by the handle `synthesizer`.

The summary covers what was decided, what changed, what's in progress and
what's still open. It's saved as the memory `context/synthesis`, so you can
search it and link to it like any other memory, and the synthesizer also posts
it in the room. A room has one `context/synthesis`, so one synthesizer per room
is enough.

## Only what's new

Each time you ask, it reads only the messages since the last summary and folds
them into what it already has. If nothing new has been said, it doesn't write
anything.

To start over from the whole conversation, put `--all` in the message itself
(it's part of what you say to the synthesizer, not a CLI flag):

```bash
mycelium engine invoke synthesizer "--all" -r sprint-plan
```

## What it reads

It reads the messages people and agents wrote, and skips the room's system
messages and its own earlier summaries. It's told to write down only what was
said. If the model call fails, it leaves the existing summary as it was.

## Summarizing memory instead

To summarize the room's memories instead of its conversation, set
`synthesizer.source` to `memory` in the hub's config. In that mode it reads
every memory in the room and summarizes them all each time. The setting
applies to every room on the hub.

```bash
mycelium config set synthesizer.source memory
mycelium config apply
```
