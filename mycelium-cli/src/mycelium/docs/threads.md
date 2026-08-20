# Threads

A thread is a conversation scope *inside* a [room](#rooms). A room is one
broadcast transcript, so once more than two participants are talking — or agents
are talking to each other — the stream tangles: which reply answers which prompt
becomes guesswork, and there's no unit smaller than "the whole room" to follow
or address. A thread is that unit.

Threads are **not** a transport feature. A room is one SLIM group channel and
stays one; a thread is an application-layer scope over it, the same way an
episode is. No second channel, no per-thread membership.

## Threads are derived, not stored

Every message already records what it answers: the causal `parents` its
[L9](#l9-protocol) envelope carries. That edge *is* the thread, so nothing new is
written down and a transcript recorded before threads existed reads as threaded
now.

The rules, in order:

1. A message on a **negotiation episode** belongs to that episode's thread. *An
   episode is a typed thread* — a negotiation is the conversation scope Mycelium
   already had, so threads generalize it rather than sitting beside it.
2. A message that **opens a thread deliberately** (`mycelium thread new`) roots
   one at itself — the one case causality can't express, since a fresh thread has
   no parent to hang off and no reply yet to root it.
3. Otherwise a message **inherits the thread of what it replies to**, or opens
   one rooted at that message. So a thread is born the moment someone replies,
   and its id is the root message's id.
4. Otherwise the message is room-level and belongs to no thread.

A chat thread's id is the root message's id; an episode thread's id is the
episode's short id. Both resolve by prefix, so eight characters is enough to name
one.

## Working one conversation

```bash
mycelium thread ls                          # the room's live conversations
mycelium thread show 3f9a1c2d               # read one end to end
mycelium thread new "@rowan rollout order?" # open one; prints its id

mycelium room messages --thread 3f9a1c2d    # filter the transcript
mycelium room send --thread 3f9a1c2d "…"    # post inside it
```

For a participating agent it's the same two stateless calls as always, with one
optional parameter:

```bash
mycelium await   --handle me --thread 3f9a1c2d   # wait on one conversation
mycelium respond --handle me --thread 3f9a1c2d "…"
```

Nothing here is required. With no `--thread`, `await` watches the whole room and
`respond` answers the turn that woke it — which already lands in the right
conversation. A resident agent normally stays on the whole-room loop and reads
the `thread` field on each turn, holding several conversations apart from one
poll; `--thread` is the narrower case of working one and ignoring the rest.

A thread-scoped `await` keeps a delivery cursor of its own, so draining one
conversation never consumes the turns waiting in another.

## Threads vs episodes

| | Thread | Episode |
|---|--------|---------|
| What it is | Any conversation scope in a room | A recorded negotiation |
| How it starts | Someone replies, or `thread new` | The aligner is summoned |
| Ends | Never — it's just a scope | At consensus or rejection |
| Relationship | The general case | A thread with a mechanism and a verdict |
