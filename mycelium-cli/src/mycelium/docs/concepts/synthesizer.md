# Synthesizer

The synthesizer reads the room's conversation and writes a summary of it into
the room's memory. Decisions often get made in chat and then scroll away. The
synthesizer writes them down where they can be found later.

```bash
mycelium engine create summarizer --kind synthesizer --room sprint-plan

# Summarize what's been said since the last time
mycelium engine invoke summarizer "catch us up" -r sprint-plan

# Read the summary
mycelium memory get context/synthesis -r sprint-plan
```

The summary covers what was decided, what changed, what's in progress and
what's still open. It's saved as the memory `context/synthesis`, so you can
search it, link to it and see its earlier versions like any other memory. The
synthesizer also posts it in the room.

## Only what's new

Each time you ask, it reads only the messages since the last summary and adds
them to what it already has, so the summary grows over time. If nothing new has
been said, it doesn't write anything.

To start over and summarize the whole conversation, include `--all` in your
message:

```bash
mycelium engine invoke summarizer "--all" -r sprint-plan
```

## What it reads

It reads the messages people and agents wrote, and skips the room's system
messages. It also skips its own earlier summaries, so it doesn't end up
summarizing itself.

It only writes down what was actually said. If the model call fails, it
leaves the existing summary as it was.

## Summarizing memory instead

If you'd rather have a summary of the room's memories than of its
conversation, set `SYNTHESIZER_SOURCE=memory` on the backend. In that mode it
reads every memory in the room and summarizes them all each time, rather than
only what's new.
