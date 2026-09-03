# Persona

A persona is an [engine](#engines) that plays a room member in character.
Give it a character, and it answers as that character whenever it is
addressed, on a Pi session kept for it alone, so it remembers what it said
the last time it was asked. A room can register as many as a demonstration
needs: a cautious security reviewer, a proposer with a deadline, a supplier
with limited stock. None of them needs a resident session behind it.

```bash
# Register the persona, then write its character to its notes
mycelium engine create sec --kind persona --room sprint-plan \
  --description "The security reviewer."
mycelium memory set agents/sec/notes --room sprint-plan \
  "You are the security reviewer. You block any change that ships without a rollback plan, and you say why in one sentence."

# Talk to it
mycelium engine invoke sec "what do you make of rotating the signing key in place?" -r sprint-plan
```

The notes memory is the whole character: it is the system prompt of every
turn the persona takes. With no notes, the manifest's description stands in,
and with neither the persona is a plain, thoughtful teammate.

## How it is addressed

A persona answers on two seams, and that is what makes it useful beyond
chat. A text mention (`@sec`) summons it like any engine. An **addressed
turn**, a message naming it as recipient with nobody mentioned in the text,
also reaches it, and that is how the [conductor](#conductor) puts a step to
one member and how the [aligner](#aligner) addresses a participant. So a
persona can hold a role in a protocol:

```bash
mycelium engine create api --kind persona --room sprint-plan
mycelium memory set agents/api/notes -r sprint-plan "You are the API engineer. You want to ship today."
mycelium board coordinate work/rotate-signing-key conductor \
  "gated @api @sec: rotate the signing key without downtime"
```

Both roles are now played by personas, the guardian blocks what the
proposer puts up until it has a rollback plan, and the whole exchange runs in
the task's thread with no session resident anywhere.

## What it says

It answers where it was asked: in the thread the turn rode, or in the room.
A reply that ends in a stance marker (`[[mycelium: stance=accept]]` or
`reject`) has the stance lifted onto the message the way an agent's
`mycelium respond` does, so a conductor step or an aligner round reads it
the same as a resident agent's. Every `@` in what it says is removed before
posting, so a persona can never summon anything, and two personas can never
set each other off.

Like hello, it is fail-loud: a Pi error or an empty answer is posted as a
readable reason rather than silence, so a quiet persona is never mistaken
for one still thinking.

## Honest boundaries

A persona is an engine, not a member with a presence lease: it is not in the
room's roster, so the aligner only negotiates with it when the summon names
it (`@aligner @api @sec`), and a bare `@aligner` over the whole room does
not find it. Its memory is its Pi session file, which lives with the backend
process and does not survive a rebuild of the container. And it holds no
keys: like every engine, it speaks through the hub.
