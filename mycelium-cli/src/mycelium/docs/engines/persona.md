# Persona

A persona is a character you write that a model plays. Describe who it is and
how it behaves, and it answers in character whenever someone talks to it. It
remembers its earlier conversations in the room.

Personas are handy for demos and for trying out a process before real people
or agents are involved. You might write a security reviewer who blocks anything
without a rollback plan, an engineer in a hurry to ship or a supplier with
limited stock.

```bash
mycelium engine create sec --kind persona --room sprint-plan \
  --description "The security reviewer."

mycelium memory set agents/sec/notes --room sprint-plan \
  "You are the security reviewer. You block any change that ships without a rollback plan, and you say why in one sentence."

mycelium engine invoke sec "what do you think of rotating the signing key in place?" -r sprint-plan
```

The character comes from the persona's notes in `agents/<handle>/notes`. Change
the notes and you change how it behaves from its next reply on. Without notes
it uses the description. Without either, it's a generic helpful teammate.

## In a flow

A persona can take a role in a [conductor](#conductor) flow, so you can run a
whole review with no one else in the room:

```bash
mycelium engine create api --kind persona --room sprint-plan
mycelium memory set agents/api/notes -r sprint-plan \
  "You are the API engineer. You want to ship today."

mycelium board coordinate work/rotate-signing-key conductor \
  "gated @api @sec: rotate the signing key without downtime"
```

The `gated` flow has two roles. Here `api` is the proposer and `sec` is the
guardian. `sec` keeps rejecting until the proposal includes a rollback plan.
Everything happens in the task's thread.

## Things to know

- **A persona can't mention anyone.** It can't start other engines or set off
  another persona, so two personas won't get stuck replying to each other.
- **It waits its turn.** In a flow, it only answers when it's asked.
- **The aligner won't include it unless you name it.** The aligner invites the
  agents that are listening in `mycelium await`, and a persona never is. Name
  it in the same message, as in `@aligner @api @sec`.
- **Its conversation history isn't room memory.** The hub keeps it alongside
  the backend, so rebuilding a Docker hub's container starts each persona's
  conversation afresh. Its character in `agents/<handle>/notes` is room memory
  and survives.
- **If something goes wrong, it says so.** An error from the model is posted in
  the room instead of a reply.
